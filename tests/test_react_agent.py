from pathlib import Path

import pytest

from evodev.agent import AgentStatus, ReActAgent
from evodev.agent.events import AgentEvent
from evodev.llm import FakeLLM, ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall, ToolProvider, ToolResult, ToolSpec
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider


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


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_steps": 0}, "max_steps"),
        ({"max_tool_retries": -1}, "max_tool_retries"),
        ({"max_context_chars": 0}, "max_context_chars"),
    ],
)
def test_agent_rejects_invalid_harness_limits(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ReActAgent(FakeLLM([]), RecordingProvider(), **kwargs)


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
        FakeLLM(
            [
                _tool_turn("first"),
                ModelTurn(content="done", input_tokens=5, output_tokens=2),
            ]
        ),
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
    final_model_event = [event for event in sink.events if event.type == "MODEL_TURN"][-1]
    assert final_model_event.data["input_tokens"] == 5
    assert final_model_event.data["output_tokens"] == 2


class SequencedProvider(ToolProvider):
    def __init__(
        self,
        responses: list[ToolResult | Exception],
        *,
        read_only: bool = True,
        idempotent: bool = True,
    ) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.spec = ToolSpec(
            name="unstable",
            description="Return a configured sequence of results.",
            input_schema={"type": "object"},
            source="fake",
            read_only=read_only,
            destructive=not read_only,
            idempotent=idempotent,
        )

    def list_tools(self) -> list[ToolSpec]:
        return [self.spec]

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _result(success: bool, error_type: str | None = None) -> ToolResult:
    return ToolResult(
        call_id="unstable-call",
        tool_name="unstable",
        success=success,
        content="ok" if success else "temporary failure",
        error_type=error_type,
        duration_ms=0,
    )


def _unstable_turn() -> ModelTurn:
    return ModelTurn(
        tool_calls=[ToolCall(call_id="unstable-call", name="unstable", arguments={})]
    )


def test_transient_read_only_tool_failure_retries_once() -> None:
    provider = SequencedProvider([_result(False, "TEMPORARY_ERROR"), _result(True)])
    sink = RecordingEventSink()

    result = ReActAgent(
        FakeLLM([_unstable_turn(), ModelTurn(content="done")]),
        provider,
        max_tool_retries=1,
        event_sink=sink,
    ).run(_task())

    assert provider.calls == 2
    assert result.tool_results[0].success is True
    assert [event.type for event in sink.events].count("TOOL_RETRY") == 1


def test_non_idempotent_tool_is_never_retried() -> None:
    provider = SequencedProvider(
        [_result(False, "TEMPORARY_ERROR")], read_only=False, idempotent=False
    )

    result = ReActAgent(
        FakeLLM([_unstable_turn(), ModelTurn(content="handled")]),
        provider,
        max_tool_retries=1,
    ).run(_task())

    assert provider.calls == 1
    assert result.tool_results[0].error_type == "TEMPORARY_ERROR"


def test_timeout_exception_is_retried_for_safe_tool() -> None:
    provider = SequencedProvider([TimeoutError("slow tool"), _result(True)])

    result = ReActAgent(
        FakeLLM([_unstable_turn(), ModelTurn(content="done")]), provider
    ).run(_task())

    assert provider.calls == 2
    assert result.tool_results[0].success is True


def test_tool_exception_becomes_result_instead_of_crashing() -> None:
    provider = SequencedProvider([ValueError("broken tool")])

    result = ReActAgent(
        FakeLLM([_unstable_turn(), ModelTurn(content="handled")]), provider
    ).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.tool_results[0].error_type == "TOOL_EXCEPTION"
    assert result.state.last_error == "TOOL_EXCEPTION"


def test_llm_exception_sets_error_state() -> None:
    result = ReActAgent(FakeLLM([RuntimeError("model unavailable")]), RecordingProvider()).run(
        _task()
    )

    assert result.status == AgentStatus.ERROR
    assert result.final_answer is None
    assert result.state.last_error == "RuntimeError: model unavailable"
