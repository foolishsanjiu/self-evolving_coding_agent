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
    tool_history: list[ToolResult] = Field(default_factory=list)
    current_patch: str | None = None
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
    if not result.success:
        state.last_error = result.error_type or result.content
        return

    if result.tool_name == "read_file" and (path := result.data.get("path")):
        state.files_inspected.add(str(path))
    elif result.tool_name == "apply_patch":
        patch = result.data.get("patch") or result.data.get("diff")
        state.current_patch = str(patch or result.content)
    elif result.tool_name == "run_tests":
        state.test_results.append(result.data)


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
