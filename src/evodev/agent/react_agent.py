"""Minimal explicit ReAct tool-calling loop."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from evodev.agent.events import AgentEvent, EventSink, NoOpEventSink
from evodev.llm.schemas import ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import ToolProvider, ToolResult, ToolSpec


class ModelClient(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> ModelTurn:
        """Generate one provider-neutral model turn."""


class AgentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    MAX_STEPS = "MAX_STEPS"


class AgentRunResult(BaseModel):
    """Minimal Task 2 outcome; Task 3 will expand runtime state."""

    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    final_answer: str | None = None
    step_count: int = Field(ge=0)
    tool_results: list[ToolResult] = Field(default_factory=list)


class ReActAgent:
    """Run a transparent Think/Act/Observe loop until final answer or budget exhaustion."""

    def __init__(
        self,
        llm: ModelClient,
        tool_provider: ToolProvider,
        max_steps: int = 15,
        event_sink: EventSink | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.llm = llm
        self.tool_provider = tool_provider
        self.max_steps = max_steps
        self.event_sink = event_sink or NoOpEventSink()

    def _emit(self, event_type: str, **data: Any) -> None:
        self.event_sink.emit(AgentEvent(type=event_type, data=data))

    def run(self, task: TaskSpec) -> AgentRunResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are EvoDev, a coding agent. Use the available tools to inspect the "
                    "workspace, then provide a concise final answer."
                ),
            },
            {"role": "user", "content": task.instruction},
        ]
        tools = self.tool_provider.list_tools()
        tool_results: list[ToolResult] = []
        self._emit("RUN_STARTED", task_id=task.task_id)

        for step_count in range(1, self.max_steps + 1):
            turn = self.llm.generate(messages=messages, tools=tools)
            self._emit(
                "MODEL_TURN",
                step_count=step_count,
                finish_reason=turn.finish_reason,
                tool_call_count=len(turn.tool_calls),
            )

            if not turn.tool_calls:
                self._emit("FINAL_ANSWER", step_count=step_count)
                self._emit("RUN_FINISHED", status=AgentStatus.SUCCESS)
                return AgentRunResult(
                    status=AgentStatus.SUCCESS,
                    final_answer=turn.content or "",
                    step_count=step_count,
                    tool_results=tool_results,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [call.model_dump() for call in turn.tool_calls],
                }
            )
            for model_call in turn.tool_calls:
                tool_call = model_call
                self._emit("TOOL_CALL", step_count=step_count, tool_call=tool_call.model_dump())
                result = self.tool_provider.call_tool(tool_call)
                tool_results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": result.content,
                    }
                )
                self._emit("TOOL_RESULT", step_count=step_count, result=result.model_dump())

        self._emit("RUN_FINISHED", status=AgentStatus.MAX_STEPS)
        return AgentRunResult(
            status=AgentStatus.MAX_STEPS,
            step_count=self.max_steps,
            tool_results=tool_results,
        )
