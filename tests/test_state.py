from pathlib import Path

from evodev.agent.state import AgentState, should_retry, update_state
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall, ToolResult, ToolSpec


def _state() -> AgentState:
    return AgentState(
        task=TaskSpec(
            task_id="state-test",
            instruction="Track state.",
            workspace_path=Path("fixtures/simple_read"),
        )
    )


def _result(
    tool_name: str,
    *,
    success: bool = True,
    error_type: str | None = None,
    **data,
) -> ToolResult:
    return ToolResult(
        call_id=f"{tool_name}-call",
        tool_name=tool_name,
        success=success,
        content="result",
        data=data,
        error_type=None if success else error_type or "FAILURE",
        duration_ms=1,
    )


def test_update_state_tracks_files_patch_tests_and_last_error() -> None:
    state = _state()

    update_state(state, _result("read_file", path="src/app.py"))
    update_state(state, _result("apply_patch", patch="diff --git a/app.py b/app.py"))
    update_state(state, _result("run_tests", exit_code=0, passed_count=3))
    update_state(state, _result("run_tests", success=False, timed_out=True))
    update_state(state, _result("read_file", success=False))

    assert state.files_inspected == {"src/app.py"}
    assert state.current_patch == "diff --git a/app.py b/app.py"
    assert state.test_results == [
        {"exit_code": 0, "passed_count": 3},
        {"timed_out": True},
    ]
    assert state.last_error == "FAILURE"
    assert len(state.tool_history) == 5


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


def test_update_state_tracks_test_inspection_before_first_edit() -> None:
    state = _state()

    update_state(
        state,
        _result(
            "search_code",
            path=".",
            matches=[{"file": "tests/test_app.py"}],
        ),
    )
    update_state(state, _result("apply_patch", patch="a patch"))
    update_state(state, _result("read_file", path="tests/test_late.py"))

    assert state.tests_inspected_before_edit is True


def test_source_inspection_does_not_count_as_test_inspection() -> None:
    state = _state()

    update_state(state, _result("read_file", path="src/app.py"))

    assert state.tests_inspected_before_edit is False


def test_patch_recovery_requires_reading_every_known_failed_patch_path() -> None:
    state = _state()
    patch_call = ToolCall(
        call_id="failed-patch",
        name="apply_patch",
        arguments={
            "patch": (
                "--- a/src/app.py\n"
                "+++ b/src/app.py\n"
                "--- a/src/config.py\n"
                "+++ b/src/config.py\n"
            )
        },
    )

    update_state(
        state,
        _result("apply_patch", success=False, error_type="PATCH_APPLY_FAILED"),
        tool_call=patch_call,
    )
    update_state(state, _result("read_file", path="unrelated.txt"))

    assert state.patch_recovery_required is True
    assert state.patch_recovery_paths == {"src/app.py", "src/config.py"}

    update_state(state, _result("read_file", path="./src/app.py"))
    assert state.patch_recovery_required is True
    assert state.patch_recovery_paths == {"src/config.py"}

    update_state(state, _result("read_file", path="src\\config.py"))
    assert state.patch_recovery_required is False
    assert state.patch_recovery_paths == set()


def test_pathless_failed_patch_keeps_compatible_read_recovery() -> None:
    state = _state()
    patch_call = ToolCall(
        call_id="failed-patch",
        name="apply_patch",
        arguments={"patch": "not a unified patch"},
    )

    update_state(
        state,
        _result("apply_patch", success=False, error_type="PATCH_APPLY_FAILED"),
        tool_call=patch_call,
    )
    update_state(state, _result("read_file", path="src/app.py"))

    assert state.patch_recovery_required is False
