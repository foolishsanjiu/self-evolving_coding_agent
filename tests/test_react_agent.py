from pathlib import Path

import pytest

from evodev.agent import AgentStatus, ExecutionGuard, ReActAgent
from evodev.agent.events import AgentEvent
from evodev.llm import FakeLLM, ModelTurn
from evodev.policy import AgentPolicy, InspectTestsMode
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


class PolicyToolProvider(ToolProvider):
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self.specs = [
            ToolSpec(
                name=name,
                description=f"Use {name}.",
                input_schema={"type": "object"},
                source="fake",
                read_only=name != "apply_patch",
                destructive=name == "apply_patch",
                idempotent=name != "apply_patch",
            )
            for name in ["read_file", "search_code", "apply_patch"]
        ]

    def list_tools(self) -> list[ToolSpec]:
        return self.specs

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        data = dict(tool_call.arguments)
        if tool_call.name == "apply_patch":
            data = {"patch": tool_call.arguments["patch"]}
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=True,
            content=f"completed {tool_call.name}",
            data=data,
            duration_ms=0,
        )


class ContractToolProvider(ToolProvider):
    def __init__(self, patch_successes: list[bool]) -> None:
        self.patch_successes = list(patch_successes)
        self.calls: list[ToolCall] = []
        self.specs = [
            ToolSpec(
                name=name,
                description=f"Use {name}.",
                input_schema={"type": "object"},
                source="fake",
                read_only=name != "apply_patch",
                destructive=name == "apply_patch",
                idempotent=name != "apply_patch",
            )
            for name in ["read_file", "apply_patch", "run_tests"]
        ]

    def list_tools(self) -> list[ToolSpec]:
        return self.specs

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        if tool_call.name == "apply_patch":
            success = self.patch_successes.pop(0)
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.name,
                success=success,
                content="patch applied" if success else "patch failed",
                data={"patch": tool_call.arguments["patch"]} if success else {},
                error_type=None if success else "PATCH_APPLY_FAILED",
                duration_ms=0,
            )
        if tool_call.name == "read_file":
            data = {"path": tool_call.arguments["path"], "content": "source"}
        else:
            data = {"exit_code": 0, "passed": True}
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=True,
            content=f"completed {tool_call.name}",
            data=data,
            duration_ms=0,
        )


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


def test_policy_max_steps_overrides_static_agent_limit() -> None:
    provider = RecordingProvider()
    turns = [_tool_turn(f"call-{index}") for index in range(10)]

    result = ReActAgent(
        FakeLLM(turns),
        provider,
        max_steps=20,
        policy=AgentPolicy(max_react_steps=10),
    ).run(_task())

    assert result.status == AgentStatus.MAX_STEPS
    assert result.step_count == 10
    assert len(provider.calls) == 10


def test_policy_require_blocks_edit_until_tests_are_inspected() -> None:
    first_edit = ToolCall(
        call_id="edit-blocked",
        name="apply_patch",
        arguments={"patch": "first patch"},
    )
    inspect_tests = ToolCall(
        call_id="read-tests",
        name="read_file",
        arguments={"path": "tests/test_app.py"},
    )
    second_edit = ToolCall(
        call_id="edit-allowed",
        name="apply_patch",
        arguments={"patch": "second patch"},
    )
    llm = FakeLLM(
        [
            ModelTurn(tool_calls=[first_edit]),
            ModelTurn(tool_calls=[inspect_tests]),
            ModelTurn(tool_calls=[second_edit]),
            ModelTurn(content="done"),
        ]
    )
    provider = PolicyToolProvider()

    result = ReActAgent(
        llm,
        provider,
        policy=AgentPolicy(inspect_tests_before_edit=InspectTestsMode.REQUIRE),
    ).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.tool_results[0].error_type == "POLICY_PRECONDITION_NOT_MET"
    assert [call.call_id for call in provider.calls] == ["read-tests", "edit-allowed"]
    assert result.state.tests_inspected_before_edit is True
    assert llm.requests[1][0][-1]["content"].startswith("Policy requires inspecting")


def test_prefer_policy_is_visible_guidance_without_hard_block() -> None:
    llm = FakeLLM([ModelTurn(content="done")])
    policy = AgentPolicy(
        inspect_tests_before_edit=InspectTestsMode.PREFER,
        prefer_search_before_read=True,
    )

    result = ReActAgent(llm, PolicyToolProvider(), policy=policy).run(_task())

    assert result.status == AgentStatus.SUCCESS
    contents = [message["content"] for message in llm.requests[0][0]]
    assert any("Prefer inspecting relevant tests" in content for content in contents)
    assert any("Prefer search_code" in content for content in contents)
    guided_tools = {
        tool.name: tool.description for tool in llm.requests[0][1] if tool.name != "apply_patch"
    }
    assert all("Policy guidance: prefer search_code" in text for text in guided_tools.values())


def test_contract_guard_blocks_patch_retry_until_file_is_reinspected() -> None:
    calls = [
        ToolCall(
            call_id="patch-fails",
            name="apply_patch",
            arguments={"patch": "--- a/app.py\n+++ b/app.py\n"},
        ),
        ToolCall(call_id="patch-blocked", name="apply_patch", arguments={"patch": "retry"}),
        ToolCall(
            call_id="read-unrelated",
            name="read_file",
            arguments={"path": "unrelated.py"},
        ),
        ToolCall(
            call_id="patch-still-blocked",
            name="apply_patch",
            arguments={"patch": "retry"},
        ),
        ToolCall(call_id="read-current", name="read_file", arguments={"path": "app.py"}),
        ToolCall(call_id="patch-works", name="apply_patch", arguments={"patch": "good"}),
        ToolCall(call_id="verify", name="run_tests", arguments={}),
    ]
    llm = FakeLLM([ModelTurn(tool_calls=[call]) for call in calls] + [ModelTurn(content="done")])
    provider = ContractToolProvider([False, True])

    result = ReActAgent(
        llm,
        provider,
        execution_guard=ExecutionGuard(
            inspect_after_patch_failure=True,
            verify_after_last_edit=True,
        ),
    ).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.tool_results[1].error_type == "CONTRACT_PRECONDITION_NOT_MET"
    assert result.tool_results[3].error_type == "CONTRACT_PRECONDITION_NOT_MET"
    assert [call.call_id for call in provider.calls] == [
        "patch-fails",
        "read-unrelated",
        "read-current",
        "patch-works",
        "verify",
    ]
    assert result.state.patch_recovery_required is False
    assert result.state.patch_needs_verification is False


def test_contract_guard_rejects_final_answer_until_latest_edit_is_verified() -> None:
    patch = ToolCall(call_id="patch", name="apply_patch", arguments={"patch": "good"})
    verify = ToolCall(call_id="verify", name="run_tests", arguments={})
    sink = RecordingEventSink()
    llm = FakeLLM(
        [
            ModelTurn(tool_calls=[patch]),
            ModelTurn(content="premature"),
            ModelTurn(tool_calls=[verify]),
            ModelTurn(content="done"),
        ]
    )

    result = ReActAgent(
        llm,
        ContractToolProvider([True]),
        event_sink=sink,
        execution_guard=ExecutionGuard(verify_after_last_edit=True),
    ).run(_task())

    assert result.status == AgentStatus.SUCCESS
    assert result.final_answer == "done"
    assert result.step_count == 4
    assert [event.type for event in sink.events].count("CONTRACT_BLOCKED") == 1
    assert any(
        "latest successful edit has not been verified" in message["content"]
        for message in llm.requests[2][0]
    )


def test_contract_guard_reserves_penultimate_step_for_verification() -> None:
    patch = ToolCall(call_id="patch", name="apply_patch", arguments={"patch": "good"})
    late_read = ToolCall(
        call_id="late-read", name="read_file", arguments={"path": "app.py"}
    )
    verify = ToolCall(call_id="verify", name="run_tests", arguments={})
    provider = ContractToolProvider([True])

    result = ReActAgent(
        FakeLLM(
            [
                ModelTurn(tool_calls=[patch]),
                ModelTurn(tool_calls=[late_read]),
                ModelTurn(tool_calls=[verify]),
            ]
        ),
        provider,
        max_steps=3,
        execution_guard=ExecutionGuard(verify_after_last_edit=True),
    ).run(_task())

    assert result.status == AgentStatus.MAX_STEPS
    assert result.tool_results[1].error_type == "CONTRACT_PRECONDITION_NOT_MET"
    assert result.tool_results[1].data["required_action"] == (
        "run_tests_before_step_budget_expires"
    )
    assert [call.call_id for call in provider.calls] == ["patch", "verify"]
    assert result.state.patch_needs_verification is False


def test_contract_guard_blocks_unverifiable_patch_on_final_step() -> None:
    read = ToolCall(call_id="read", name="read_file", arguments={"path": "app.py"})
    late_patch = ToolCall(
        call_id="late-patch", name="apply_patch", arguments={"patch": "too late"}
    )
    provider = ContractToolProvider([])

    result = ReActAgent(
        FakeLLM([ModelTurn(tool_calls=[read]), ModelTurn(tool_calls=[late_patch])]),
        provider,
        max_steps=2,
        execution_guard=ExecutionGuard(verify_after_last_edit=True),
    ).run(_task())

    assert result.status == AgentStatus.MAX_STEPS
    assert result.tool_results[-1].error_type == "CONTRACT_PRECONDITION_NOT_MET"
    assert result.tool_results[-1].data["required_action"] == (
        "do_not_edit_without_verification_budget"
    )
    assert [call.call_id for call in provider.calls] == ["read"]
    assert result.state.current_patch is None


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
