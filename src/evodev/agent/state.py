"""Task-local state and small state-transition helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evodev.schemas import TaskSpec
from evodev.tools import ToolResult, ToolSpec


class AgentStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    MAX_STEPS = "MAX_STEPS"
    ERROR = "ERROR"


class AgentState(BaseModel):
    """Mutable working state for one coding task."""

    model_config = ConfigDict(extra="forbid")

    task: TaskSpec
    status: AgentStatus = AgentStatus.RUNNING
    step_count: int = Field(default=0, ge=0)
    files_inspected: set[str] = Field(default_factory=set)
    tests_inspected_before_edit: bool = False
    tool_history: list[ToolResult] = Field(default_factory=list)
    current_patch: str | None = None
    patch_recovery_required: bool = False
    patch_needs_verification: bool = False
    contract_feedback: str | None = None
    test_results: list[dict[str, Any]] = Field(default_factory=list)
    last_error: str | None = None


TRANSIENT_TOOL_ERRORS = frozenset(
    {
        "TOOL_TIMEOUT",
        "TEMPORARY_ERROR",
        "RATE_LIMITED",
        "MCP_TIMEOUT",
        "MCP_CONNECTION_ERROR",
    }
)


def update_state(state: AgentState, result: ToolResult) -> None:
    """Apply one final tool result to the current task state."""
    state.tool_history.append(result)
    if result.tool_name == "run_tests" and result.data:
        state.test_results.append(result.data)
        state.patch_needs_verification = False
    if not result.success:
        if result.tool_name == "apply_patch" and result.error_type == "PATCH_APPLY_FAILED":
            state.patch_recovery_required = True
        state.last_error = result.error_type or result.content
        return

    if result.tool_name == "read_file" and (path := result.data.get("path")):
        state.patch_recovery_required = False
        path = str(path)
        state.files_inspected.add(path)
        if state.current_patch is None and _is_test_path(path):
            state.tests_inspected_before_edit = True
    elif result.tool_name == "search_code" and state.current_patch is None:
        paths = [str(result.data.get("path", ""))]
        paths.extend(str(match.get("file", "")) for match in result.data.get("matches", []))
        if any(_is_test_path(path) for path in paths):
            state.tests_inspected_before_edit = True
    elif result.tool_name == "apply_patch":
        patch = result.data.get("patch") or result.data.get("diff")
        state.current_patch = str(patch or result.content)
        state.patch_recovery_required = False
        state.patch_needs_verification = True


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/").lower()
    parts = normalized.split("/")
    filename = parts[-1] if parts else ""
    return "tests" in parts or filename.startswith("test_") or filename.endswith("_test.py")


def should_retry(
    tool: ToolSpec | None,
    result: ToolResult,
    retries_used: int,
    max_tool_retries: int,
) -> bool:
    """Retry only transient failures from tools declared read-only and idempotent."""
    return bool(
        tool
        and tool.read_only
        and tool.idempotent
        and not result.success
        and result.error_type in TRANSIENT_TOOL_ERRORS
        and retries_used < max_tool_retries
    )
