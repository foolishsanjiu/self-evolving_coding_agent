"""Explicit ReAct loop with task state, bounded context, and safe retries."""

from __future__ import annotations

import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from evodev.agent.context import ContextManager
from evodev.agent.contracts import ExecutionGuard
from evodev.agent.events import AgentEvent, EventSink, NoOpEventSink
from evodev.agent.state import AgentState, AgentStatus, should_retry, update_state
from evodev.llm.schemas import ModelTurn
from evodev.policy import AgentPolicy, InspectTestsMode
from evodev.schemas import TaskSpec
from evodev.tools import ToolCall, ToolProvider, ToolResult, ToolSpec

SYSTEM_PROMPT = (
    "You are EvoDev, a coding agent. Use the available tools to inspect the workspace, "
    "then provide a concise final answer."
)


class ModelClient(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> ModelTurn:
        """Generate one provider-neutral model turn."""


class AgentRunResult(BaseModel):
    """Final answer together with the complete task-local state."""

    model_config = ConfigDict(extra="forbid")

    state: AgentState
    final_answer: str | None = None

    @property
    def status(self) -> AgentStatus:
        return self.state.status

    @property
    def step_count(self) -> int:
        return self.state.step_count

    @property
    def tool_results(self) -> list[ToolResult]:
        return self.state.tool_history


class ReActAgent:
    """Run a transparent Think/Act/Observe loop until completion or a hard limit."""

    def __init__(
        self,
        llm: ModelClient,
        tool_provider: ToolProvider,
        max_steps: int = 15,
        max_tool_retries: int = 1,
        max_context_chars: int = 60_000,
        event_sink: EventSink | None = None,
        experience_section: str = "",
        execution_guard: ExecutionGuard | None = None,
        policy: AgentPolicy | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_tool_retries < 0:
            raise ValueError("max_tool_retries cannot be negative")
        if max_context_chars < 1:
            raise ValueError("max_context_chars must be at least 1")
        self.llm = llm
        self.tool_provider = tool_provider
        self.max_steps = policy.max_react_steps if policy is not None else max_steps
        self.max_tool_retries = max_tool_retries
        self.max_context_chars = max_context_chars
        self.event_sink = event_sink or NoOpEventSink()
        self.experience_section = experience_section
        self.execution_guard = execution_guard or ExecutionGuard()
        self.policy = policy

    def _emit(self, event_type: str, **data: Any) -> None:
        self.event_sink.emit(AgentEvent(type=event_type, data=data))

    def _tool_exception_result(
        self, tool_call: ToolCall, exc: Exception, started: float
    ) -> ToolResult:
        error_type = "TOOL_TIMEOUT" if isinstance(exc, TimeoutError) else "TOOL_EXCEPTION"
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=False,
            content=f"{type(exc).__name__}: {exc}",
            error_type=error_type,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    def _call_tool(self, tool_call: ToolCall, tool: ToolSpec | None) -> ToolResult:
        retries_used = 0
        while True:
            started = time.perf_counter()
            try:
                result = self.tool_provider.call_tool(tool_call)
            except Exception as exc:
                result = self._tool_exception_result(tool_call, exc, started)
            if not should_retry(tool, result, retries_used, self.max_tool_retries):
                return result
            retries_used += 1
            self._emit(
                "TOOL_RETRY",
                tool_call=tool_call.model_dump(),
                retry_number=retries_used,
                error_type=result.error_type,
            )

    def _policy_guard(
        self, tool_call: ToolCall, state: AgentState
    ) -> ToolResult | None:
        if not (
            self.policy
            and self.policy.inspect_tests_before_edit == InspectTestsMode.REQUIRE
            and tool_call.name == "apply_patch"
            and not state.tests_inspected_before_edit
        ):
            return None
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=False,
            content=(
                "Policy requires inspecting relevant tests before apply_patch. "
                "Use read_file or search_code on the test suite, then retry the edit."
            ),
            error_type="POLICY_PRECONDITION_NOT_MET",
            data={"required_action": "inspect_relevant_tests_before_edit"},
            duration_ms=0,
        )

    def _contract_tool_guard(
        self, tool_call: ToolCall, state: AgentState
    ) -> ToolResult | None:
        if (
            self.execution_guard.verify_after_last_edit
            and state.patch_needs_verification
            and state.step_count >= self.max_steps - 1
            and tool_call.name != "run_tests"
        ):
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.name,
                success=False,
                content=(
                    "Execution contract reserves the remaining step budget for verification. "
                    "Run tests for the latest successful edit now."
                ),
                error_type="CONTRACT_PRECONDITION_NOT_MET",
                data={"required_action": "run_tests_before_step_budget_expires"},
                duration_ms=0,
            )
        if (
            self.execution_guard.verify_after_last_edit
            and tool_call.name == "apply_patch"
            and state.step_count == self.max_steps
        ):
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.name,
                success=False,
                content=(
                    "Execution contract blocks a new patch on the final step because no "
                    "verification step would remain."
                ),
                error_type="CONTRACT_PRECONDITION_NOT_MET",
                data={"required_action": "do_not_edit_without_verification_budget"},
                duration_ms=0,
            )
        if not (
            self.execution_guard.inspect_after_patch_failure
            and tool_call.name == "apply_patch"
            and state.patch_recovery_required
        ):
            return None
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=False,
            content=(
                "Execution contract blocks another patch after PATCH_APPLY_FAILED. "
                "Read the current target file, then retry with current context."
            ),
            error_type="CONTRACT_PRECONDITION_NOT_MET",
            data={"required_action": "read_current_file_after_patch_failure"},
            duration_ms=0,
        )

    def _final_contract_feedback(self, state: AgentState) -> str | None:
        if self.execution_guard.verify_after_last_edit and state.patch_needs_verification:
            return (
                "The latest successful edit has not been verified. "
                "Call run_tests before providing the final answer."
            )
        return None

    def _policy_tool_guidance(self, tools: list[ToolSpec]) -> list[ToolSpec]:
        if not (self.policy and self.policy.prefer_search_before_read):
            return tools
        guidance = " Policy guidance: prefer search_code before broad read_file exploration."
        return [
            tool.model_copy(update={"description": tool.description + guidance})
            if tool.name in {"search_code", "read_file"}
            else tool
            for tool in tools
        ]

    def run(self, task: TaskSpec) -> AgentRunResult:
        state = AgentState(task=task)
        context = ContextManager(
            system_prompt=SYSTEM_PROMPT,
            task=task,
            max_context_chars=self.max_context_chars,
            experience_section=self.experience_section,
            policy_section=self.policy.guidance() if self.policy else "",
        )
        self._emit("RUN_STARTED", task_id=task.task_id)

        try:
            tools = self._policy_tool_guidance(self.tool_provider.list_tools())
            tools_by_name = {tool.name: tool for tool in tools}
            for step_count in range(1, self.max_steps + 1):
                state.step_count = step_count
                if state.contract_feedback and not self._final_contract_feedback(state):
                    state.contract_feedback = None
                turn = self.llm.generate(messages=context.build_messages(state), tools=tools)
                self._emit(
                    "MODEL_TURN",
                    step_count=step_count,
                    finish_reason=turn.finish_reason,
                    tool_call_count=len(turn.tool_calls),
                    input_tokens=turn.input_tokens,
                    output_tokens=turn.output_tokens,
                )

                if not turn.tool_calls:
                    if feedback := self._final_contract_feedback(state):
                        state.contract_feedback = feedback
                        self._emit(
                            "CONTRACT_BLOCKED",
                            step_count=step_count,
                            required_action="run_tests_after_last_edit",
                        )
                        continue
                    state.status = AgentStatus.SUCCESS
                    self._emit(
                        "FINAL_ANSWER",
                        step_count=step_count,
                        content=turn.content or "",
                    )
                    self._emit("RUN_FINISHED", status=state.status.value)
                    return AgentRunResult(state=state, final_answer=turn.content or "")

                exchange_results = []
                for tool_call in turn.tool_calls:
                    self._emit(
                        "TOOL_CALL", step_count=step_count, tool_call=tool_call.model_dump()
                    )
                    result = (
                        self._policy_guard(tool_call, state)
                        or self._contract_tool_guard(tool_call, state)
                        or self._call_tool(tool_call, tools_by_name.get(tool_call.name))
                    )
                    update_state(state, result, tool_call=tool_call)
                    exchange_results.append(result)
                    self._emit(
                        "TOOL_RESULT", step_count=step_count, result=result.model_dump()
                    )
                context.add_exchange(turn, exchange_results)

            state.status = AgentStatus.MAX_STEPS
            self._emit("RUN_FINISHED", status=state.status.value)
            return AgentRunResult(state=state)
        except Exception as exc:
            state.status = AgentStatus.ERROR
            state.last_error = f"{type(exc).__name__}: {exc}"
            self._emit("RUN_ERROR", error=state.last_error)
            self._emit("RUN_FINISHED", status=state.status.value)
            return AgentRunResult(state=state)
