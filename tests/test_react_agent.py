from pathlib import Path
from typing import Any

from evodev.agent import AgentStatus, ReActAgent
from evodev.agent.events import AgentEvent
from evodev.llm.schemas import ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall, ToolProvider, ToolResult, ToolSpec
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider


class FakeLLM:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[tuple[list[dict[str, Any]], list[ToolSpec]]] = []

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> ModelTurn:
        self.requests.append((list(messages), list(tools or [])))
        return self.turns.pop(0)


class RecordingProvider(ToolProvider):
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self.spec = ToolSpec(
            name="inspect",
            description="Inspect a named item.",
            input_schema={"type": "object"},
            source="fake",
            read_only=True,
            destructive=False,
            idempotent=True,
        )

    def list_tools(self) -> list[ToolSpec]:
        return [self.spec]

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=True,
            content=f"inspected {tool_call.arguments['name']}",
            data={"name": tool_call.arguments["name"]},
            duration_ms=0,
        )


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task-2-test",
        instruction="Inspect the fixture.",
        workspace_path=Path("fixtures/simple_read"),
    )


def _tool_turn(call_id: str, name: str = "inspect") -> ModelTurn:
    return ModelTurn(
        tool_calls=[ToolCall(call_id=call_id, name=name, arguments={"name": call_id})],
        finish_reason="tool_calls",
    )


def test_agent_can_return_direct_final_answer() -> None:
    llm = FakeLLM([ModelTurn(content="done", finish_reason="stop")])
    provider = RecordingProvider()

    result = ReActAgent(llm, provider).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.final_answer == "done"
    assert result.step_count == 1
    assert provider.calls == []


def test_agent_supports_consecutive_tool_calls_and_observations() -> None:
    llm = FakeLLM([_tool_turn("first"), _tool_turn("second"), ModelTurn(content="done")])
    provider = RecordingProvider()

    result = ReActAgent(llm, provider).run(_task())

    assert [call.call_id for call in provider.calls] == ["first", "second"]
    assert result.status == AgentStatus.SUCCESS
    assert result.step_count == 3
    assert llm.requests[1][0][-1] == {
        "role": "tool",
        "tool_call_id": "first",
        "content": "inspected first",
    }


def test_agent_supports_multiple_calls_in_one_model_turn() -> None:
    turn = ModelTurn(
        tool_calls=[
            ToolCall(call_id="one", name="inspect", arguments={"name": "one"}),
            ToolCall(call_id="two", name="inspect", arguments={"name": "two"}),
        ]
    )
    provider = RecordingProvider()

    result = ReActAgent(FakeLLM([turn, ModelTurn(content="done")]), provider).run(_task())

    assert [call.call_id for call in provider.calls] == ["one", "two"]
    assert [item.call_id for item in result.tool_results] == ["one", "two"]


def test_invalid_tool_arguments_are_returned_to_model() -> None:
    invalid_turn = ModelTurn(
        tool_calls=[
            ToolCall(
                call_id="invalid",
                name="read_file",
                arguments={"path": "README.md", "start_line": 0},
            )
        ]
    )
    llm = FakeLLM([invalid_turn, ModelTurn(content="corrected")])
    provider = NativeToolProvider(DevToolsService(Path("fixtures/simple_read")))

    result = ReActAgent(llm, provider).run(_task())

    assert result.tool_results[0].error_type == "INVALID_TOOL_ARGUMENTS"
    assert llm.requests[1][0][-1]["tool_call_id"] == "invalid"


def test_tool_failure_does_not_crash_agent() -> None:
    missing_turn = ModelTurn(
        tool_calls=[
            ToolCall(
                call_id="missing",
                name="read_file",
                arguments={"path": "missing.py"},
            )
        ]
    )
    provider = NativeToolProvider(DevToolsService(Path("fixtures/simple_read")))

    result = ReActAgent(
        FakeLLM([missing_turn, ModelTurn(content="handled")]), provider
    ).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.tool_results[0].error_type == "FILE_NOT_FOUND"


def test_agent_stops_at_max_steps() -> None:
    provider = RecordingProvider()

    result = ReActAgent(
        FakeLLM([_tool_turn("first"), _tool_turn("second")]), provider, max_steps=2
    ).run(_task())

    assert result.status == AgentStatus.MAX_STEPS
    assert result.final_answer is None
    assert result.step_count == 2


def test_agent_emits_events_through_replaceable_sink() -> None:
    sink = RecordingEventSink()
    agent = ReActAgent(
        FakeLLM([_tool_turn("first"), ModelTurn(content="done")]),
        RecordingProvider(),
        event_sink=sink,
    )

    agent.run(_task())

    assert [event.type for event in sink.events] == [
        "RUN_STARTED",
        "MODEL_TURN",
        "TOOL_CALL",
        "TOOL_RESULT",
        "MODEL_TURN",
        "FINAL_ANSWER",
        "RUN_FINISHED",
    ]
