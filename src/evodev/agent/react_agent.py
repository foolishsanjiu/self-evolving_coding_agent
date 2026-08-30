"""Explicit ReAct loop with task state, bounded context, and safe retries."""

from __future__ import annotations

import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from evodev.agent.context import ContextManager
from evodev.agent.events import AgentEvent, EventSink, NoOpEventSink
from evodev.agent.state import AgentState, AgentStatus, should_retry, update_state
from evodev.llm.schemas import ModelTurn
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
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_tool_retries < 0:
            raise ValueError("max_tool_retries cannot be negative")
        if max_context_chars < 1:
            raise ValueError("max_context_chars must be at least 1")
        self.llm = llm
        self.tool_provider = tool_provider
        self.max_steps = max_steps
        self.max_tool_retries = max_tool_retries
        self.max_context_chars = max_context_chars
        self.event_sink = event_sink or NoOpEventSink()

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

    def run(self, task: TaskSpec) -> AgentRunResult:
        state = AgentState(task=task)
        context = ContextManager(
            system_prompt=SYSTEM_PROMPT,
            task=task,
            max_context_chars=self.max_context_chars,
        )
        self._emit("RUN_STARTED", task_id=task.task_id)

        try:
            tools = self.tool_provider.list_tools()
            tools_by_name = {tool.name: tool for tool in tools}
            for step_count in range(1, self.max_steps + 1):
                state.step_count = step_count
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
                    result = self._call_tool(tool_call, tools_by_name.get(tool_call.name))
                    update_state(state, result)
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
