from pathlib import Path

from evodev.agent.context import ContextManager
from evodev.agent.state import AgentState
from evodev.llm import ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall, ToolResult


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="context-test",
        instruction="Keep this task description.",
        workspace_path=Path("fixtures/simple_read"),
    )


def _exchange(index: int, content_size: int = 220) -> tuple[ModelTurn, list[ToolResult]]:
    call_id = f"read-{index}"
    turn = ModelTurn(
        tool_calls=[
            ToolCall(call_id=call_id, name="read_file", arguments={"path": f"file-{index}.py"})
        ]
    )
    result = ToolResult(
        call_id=call_id,
        tool_name="read_file",
        success=True,
        content=f"RAW-{index}-" + "x" * content_size,
        data={"path": f"file-{index}.py", "start_line": 1, "end_line": 20},
        duration_ms=1,
    )
    return turn, [result]


def test_context_trimming_preserves_invariants_and_summarizes_old_results() -> None:
    task = _task()
    state = AgentState(task=task)
    state.current_patch = "current-patch"
    state.test_results.append({"passed_count": 4, "failed_count": 0})
    manager = ContextManager("system-instructions", task, max_context_chars=1_050)
    for index in range(5):
        manager.add_exchange(*_exchange(index))

    messages = manager.build_messages(state)
    serialized = str(messages)

    assert messages[0]["content"] == "system-instructions"
    assert messages[1]["content"] == task.instruction
    assert "current-patch" in serialized
    assert "passed_count" in serialized
    assert "RAW-4" in serialized
    assert "RAW-0" not in serialized
    assert "Earlier tool activity" in serialized
    assert "Read file-0.py lines 1-20" in serialized
    assert manager.context_chars(messages) <= manager.max_context_chars


def test_context_without_history_contains_system_and_task() -> None:
    task = _task()
    manager = ContextManager("system-instructions", task)

    messages = manager.build_messages(AgentState(task=task))

    assert messages == [
        {"role": "system", "content": "system-instructions"},
        {"role": "user", "content": task.instruction},
    ]
