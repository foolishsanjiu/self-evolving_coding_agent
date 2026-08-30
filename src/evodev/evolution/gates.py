"""Deterministic schema, smoke, and resolution-first validation gates."""

from __future__ import annotations

from pathlib import Path

from evodev.agent import AgentStatus, ReActAgent
from evodev.llm import FakeLLM, ModelTurn
from evodev.policy.models import FROZEN_INVARIANTS, PolicyStatus, VersionedPolicy
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider

from .models import (
    GateDecision,
    PairwiseGateReport,
    PolicyArmMetrics,
    SchemaGateReport,
    SmokeGateReport,
)


def validate_policy_schema(
    champion: VersionedPolicy, candidate: VersionedPolicy
) -> SchemaGateReport:
    mutation = candidate.mutation
    changed = {
        field
        for field in type(champion.policy).model_fields
        if getattr(champion.policy, field) != getattr(candidate.policy, field)
    }
    checks = {
        "policy_schema_valid": set(type(candidate.policy).model_fields)
        == {
            "inspect_tests_before_edit",
            "prefer_search_before_read",
            "max_react_steps",
        },
        "single_mutation": mutation is not None and len(changed) == 1,
        "mutation_matches_change": bool(mutation and changed == {mutation.field}),
        "parent_is_champion": candidate.parent_id == champion.policy_id,
        "candidate_status": candidate.status == PolicyStatus.CANDIDATE,
        "content_hash_valid": candidate.content_hash == candidate.policy.content_hash(),
        "frozen_invariants_intact": all(FROZEN_INVARIANTS.model_dump().values()),
        "train_evidence_only": bool(
            mutation and all(item.split == "train" for item in mutation.evidence)
        ),
    }
    passed = all(checks.values())
    failed = [name for name, value in checks.items() if not value]
    reason = "Schema and safety checks passed." if passed else f"Failed checks: {failed}"
    return SchemaGateReport(
        candidate_id=candidate.policy_id,
        passed=passed,
        checks=checks,
        reason=reason,
    )


def run_smoke_gate(
    candidate: VersionedPolicy,
    project_root: Path,
) -> SmokeGateReport:
    """Exercise startup, tools, and the optional hard guard on simple_read."""
    fixture = project_root.resolve() / "fixtures" / "simple_read"
    turns = []
    if candidate.policy.inspect_tests_before_edit == "require":
        turns.append(
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="blocked-edit",
                        name="apply_patch",
                        arguments={"patch": "not applied by the guard"},
                    )
                ]
            )
        )
    turns.extend(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="inspect-tests",
                        name="read_file",
                        arguments={"path": "tests/test_calculator.py"},
                    )
                ]
            ),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="search-source",
                        name="search_code",
                        arguments={"query": "def multiply", "path": "src"},
                    )
                ]
            ),
            ModelTurn(content="smoke complete", finish_reason="stop"),
        ]
    )
    result = ReActAgent(
        FakeLLM(turns),
        NativeToolProvider(DevToolsService(fixture)),
        policy=candidate.policy,
    ).run(
        TaskSpec(
            task_id="policy-smoke",
            instruction="Inspect the development fixture without editing it.",
            workspace_path=fixture,
        )
    )
    failures = sum(
        item.error_type == "POLICY_PRECONDITION_NOT_MET" for item in result.tool_results
    )
    expected_failures = int(candidate.policy.inspect_tests_before_edit == "require")
    passed = (
        result.status == AgentStatus.SUCCESS
        and result.final_answer == "smoke complete"
        and failures == expected_failures
        and any(item.success for item in result.tool_results)
    )
    return SmokeGateReport(
        candidate_id=candidate.policy_id,
        passed=passed,
        fixture="fixtures/simple_read",
        agent_status=result.status.value,
        react_steps=result.step_count,
        tool_calls=len(result.tool_results),
        policy_precondition_failures=failures,
        reason="Smoke fixture passed." if passed else "Agent or policy smoke behavior failed.",
    )


def compare_pairwise_validation(
    champion: PolicyArmMetrics,
    candidate: PolicyArmMetrics,
    *,
    candidate_id: str,
    controlled_conditions_match: bool,
    significant_cost_reduction: float = 0.1,
) -> PairwiseGateReport:
    task_sets_match = set(champion.task_resolutions) == set(candidate.task_resolutions)
    complete = (
        champion.total_attempts == champion.valid_attempts == 9
        and candidate.total_attempts == candidate.valid_attempts == 9
        and len(champion.task_resolutions) == len(candidate.task_resolutions) == 3
        and task_sets_match
    )
    catastrophic = sorted(
        task_id
        for task_id, resolved in champion.task_resolutions.items()
        if resolved >= 2 and candidate.task_resolutions.get(task_id) == 0
    )

    if not controlled_conditions_match or not complete:
        decision = GateDecision.INCONCLUSIVE
        reason = "Controlled conditions or the required 3x3 valid attempts are incomplete."
    elif catastrophic:
        decision = GateDecision.REJECT
        reason = f"Catastrophic regression on previously stable tasks: {catastrophic}"
    elif candidate.resolved_attempts > champion.resolved_attempts:
        decision = GateDecision.ACCEPT
        reason = "Candidate resolution improved under identical conditions."
    elif candidate.resolved_attempts < champion.resolved_attempts:
        decision = GateDecision.REJECT
        reason = "Candidate resolution declined; efficiency cannot override resolution."
    else:
        token_reduction = _relative_reduction(
            champion.average_tokens, candidate.average_tokens
        )
        supporting_reductions = [
            _relative_reduction(champion.average_react_steps, candidate.average_react_steps),
            _relative_reduction(champion.average_tool_calls, candidate.average_tool_calls),
            _relative_reduction(champion.average_latency_ms, candidate.average_latency_ms),
        ]
        if token_reduction >= significant_cost_reduction and any(
            value >= significant_cost_reduction for value in supporting_reductions
        ):
            decision = GateDecision.ACCEPT
            reason = "Resolution tied while tokens and another cost metric improved materially."
        else:
            decision = GateDecision.REJECT
            reason = "Resolution tied without a material, corroborated cost reduction."

    return PairwiseGateReport(
        candidate_id=candidate_id,
        decision=decision,
        reason=reason,
        champion=champion,
        candidate=candidate,
        controlled_conditions_match=controlled_conditions_match,
        catastrophic_regressions=catastrophic,
        significant_cost_reduction=significant_cost_reduction,
    )


def _relative_reduction(baseline: float, treatment: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - treatment) / baseline
