"""Translate selected structured Experience contracts into runtime guards."""

from typing import Any

from evodev.agent import ExecutionGuard
from evodev.agent.patch_recovery import extract_patch_paths, normalize_tool_path
from evodev.experience.models import RetrievalResult


def build_execution_guard(retrieval: RetrievalResult) -> ExecutionGuard:
    guardrails = [
        item.experience.execution_contract.guardrails
        for item in retrieval.selected
        if item.experience.execution_contract is not None
        and item.experience.execution_contract.guardrails is not None
    ]
    return ExecutionGuard(
        inspect_after_patch_failure=any(item.inspect_after_patch_failure for item in guardrails),
        verify_after_last_edit=any(item.verify_after_last_edit for item in guardrails),
    )


def analyze_guardrail_trace(events: list[dict[str, Any]]) -> dict[str, bool | int | str]:
    """Measure enforceable contract violations from public tool events."""
    patch_attempts = 0
    patch_failures = 0
    uninspected_patch_retries = 0
    blocked_uninspected_patch_retries = 0
    verification_window_blocks = 0
    final_answer_blocks = 0
    total_contract_blocks = 0
    test_calls = 0
    test_executions = 0
    recovery_required = False
    recovery_paths: set[str] = set()
    pending_patch_paths: dict[str, set[str]] = {}
    consecutive_failures = 0
    max_consecutive_failures = 0
    patch_needs_verification = False
    finish_status = "UNKNOWN"

    for event in events:
        event_type = event.get("type")
        data = event.get("data", {})
        if event_type == "TOOL_CALL":
            tool_call = data.get("tool_call", {})
            tool_name = tool_call.get("name")
            if tool_name == "apply_patch":
                patch_attempts += 1
                if recovery_required:
                    uninspected_patch_retries += 1
                call_id = str(tool_call.get("call_id", ""))
                pending_patch_paths[call_id] = extract_patch_paths(
                    tool_call.get("arguments", {}).get("patch")
                )
            elif tool_name == "run_tests":
                test_calls += 1
        elif event_type == "TOOL_RESULT":
            result = data.get("result", {})
            tool_name = result.get("tool_name")
            required_action = result.get("data", {}).get("required_action")
            if result.get("error_type") == "CONTRACT_PRECONDITION_NOT_MET":
                total_contract_blocks += 1
                if (
                    tool_name == "apply_patch"
                    and required_action == "read_current_file_after_patch_failure"
                ):
                    blocked_uninspected_patch_retries += 1
                elif required_action in {
                    "run_tests_before_step_budget_expires",
                    "do_not_edit_without_verification_budget",
                }:
                    verification_window_blocks += 1
            if tool_name == "apply_patch":
                call_id = str(result.get("call_id", ""))
                attempted_paths = pending_patch_paths.pop(call_id, set())
                if result.get("success"):
                    recovery_required = False
                    recovery_paths.clear()
                    consecutive_failures = 0
                    patch_needs_verification = True
                elif result.get("error_type") == "PATCH_APPLY_FAILED":
                    patch_failures += 1
                    recovery_required = True
                    recovery_paths = attempted_paths
                    consecutive_failures += 1
                    max_consecutive_failures = max(max_consecutive_failures, consecutive_failures)
            elif tool_name == "read_file" and result.get("success"):
                path = result.get("data", {}).get("path")
                if recovery_required and path:
                    if recovery_paths:
                        recovery_paths.discard(normalize_tool_path(str(path)))
                        recovery_required = bool(recovery_paths)
                    else:
                        recovery_required = False
                    if not recovery_required:
                        consecutive_failures = 0
            elif tool_name == "run_tests" and result.get("data"):
                test_executions += 1
                patch_needs_verification = False
        elif event_type == "RUN_FINISHED":
            finish_status = str(data.get("status", "UNKNOWN"))
        elif event_type == "CONTRACT_BLOCKED":
            total_contract_blocks += 1
            if data.get("required_action") == "run_tests_after_last_edit":
                final_answer_blocks += 1

    return {
        "patch_attempts": patch_attempts,
        "patch_failures": patch_failures,
        "uninspected_patch_retries": uninspected_patch_retries,
        "uninspected_patch_retry_attempts": uninspected_patch_retries,
        "blocked_uninspected_patch_retries": blocked_uninspected_patch_retries,
        "executed_uninspected_patch_retries": max(
            0, uninspected_patch_retries - blocked_uninspected_patch_retries
        ),
        "verification_window_blocks": verification_window_blocks,
        "final_answer_blocks": final_answer_blocks,
        "total_contract_blocks": total_contract_blocks,
        "max_consecutive_patch_failures": max_consecutive_failures,
        "test_calls": test_calls,
        "test_executions": test_executions,
        "last_successful_edit_verified": not patch_needs_verification,
        "finish_status": finish_status,
    }
