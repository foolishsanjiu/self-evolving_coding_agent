from pathlib import Path

from evodev.agent.state import AgentState, should_retry, update_state
from evodev.schemas import TaskSpec
from evodev.tools import ToolResult, ToolSpec


def _state() -> AgentState:
    return AgentState(
        task=TaskSpec(
            task_id="state-test",
            instruction="Track state.",
            workspace_path=Path("fixtures/simple_read"),
        )
    )


def _result(tool_name: str, *, success: bool = True, **data) -> ToolResult:
    return ToolResult(
        call_id=f"{tool_name}-call",
        tool_name=tool_name,
        success=success,
        content="result",
        data=data,
        error_type=None if success else "FAILURE",
        duration_ms=1,
    )


def test_update_state_tracks_files_patch_tests_and_last_error() -> None:
    state = _state()

    update_state(state, _result("read_file", path="src/app.py"))
    update_state(state, _result("apply_patch", patch="diff --git a/app.py b/app.py"))
    update_state(state, _result("run_tests", exit_code=0, passed_count=3))
    update_state(state, _result("read_file", success=False))

    assert state.files_inspected == {"src/app.py"}
    assert state.current_patch == "diff --git a/app.py b/app.py"
    assert state.test_results == [{"exit_code": 0, "passed_count": 3}]
    assert state.last_error == "FAILURE"
    assert len(state.tool_history) == 4


def test_should_retry_requires_transient_read_only_idempotent_failure() -> None:
    safe_tool = ToolSpec(
        name="read",
        description="Read.",
        input_schema={},
        source="fake",
        read_only=True,
        destructive=False,
        idempotent=True,
    )
    unsafe_tool = safe_tool.model_copy(
        update={"name": "write", "read_only": False, "destructive": True, "idempotent": False}
    )
    transient = ToolResult(
        call_id="call",
        tool_name="read",
        success=False,
        content="timeout",
        error_type="TOOL_TIMEOUT",
        duration_ms=1,
    )

    assert should_retry(safe_tool, transient, retries_used=0, max_tool_retries=1)
    assert not should_retry(safe_tool, transient, retries_used=1, max_tool_retries=1)
    assert not should_retry(unsafe_tool, transient, retries_used=0, max_tool_retries=1)
