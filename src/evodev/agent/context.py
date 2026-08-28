"""Deterministic context construction and character-budget trimming."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from evodev.agent.state import AgentState
from evodev.llm.schemas import ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import ToolResult


@dataclass(frozen=True)
class ContextExchange:
    turn: ModelTurn
    results: tuple[ToolResult, ...]


class ContextManager:
    """Keep recent exchanges verbatim and summarize older tool activity."""

    def __init__(
        self,
        system_prompt: str,
        task: TaskSpec,
        max_context_chars: int = 60_000,
        recent_tool_results: int = 6,
    ) -> None:
        if max_context_chars < 1:
            raise ValueError("max_context_chars must be at least 1")
        if not 4 <= recent_tool_results <= 6:
            raise ValueError("recent_tool_results must be between 4 and 6")
        self.system_prompt = system_prompt
        self.task = task
        self.max_context_chars = max_context_chars
        self.recent_tool_results = recent_tool_results
        self._exchanges: list[ContextExchange] = []

    def add_exchange(self, turn: ModelTurn, results: list[ToolResult]) -> None:
        self._exchanges.append(ContextExchange(turn=turn, results=tuple(results)))

    @staticmethod
    def context_chars(messages: list[dict[str, Any]]) -> int:
        return len(json.dumps(messages, ensure_ascii=False, sort_keys=True))

    def _base_messages(self, state: AgentState) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.task.instruction},
        ]
        state_lines = []
        if state.current_patch:
            state_lines.append(f"Current patch:\n{state.current_patch}")
        if state.test_results:
            state_lines.append(
                "Latest test result:\n"
                + json.dumps(state.test_results[-1], ensure_ascii=False, sort_keys=True)
            )
        if state_lines:
            messages.append({"role": "system", "content": "\n\n".join(state_lines)})
        return messages

    @staticmethod
    def _exchange_messages(exchange: ContextExchange) -> list[dict[str, Any]]:
        messages = [
            {
                "role": "assistant",
                "content": exchange.turn.content,
                "tool_calls": [call.model_dump() for call in exchange.turn.tool_calls],
            }
        ]
        messages.extend(
            {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": result.content,
            }
            for result in exchange.results
        )
        return messages

    @staticmethod
    def _result_summary(result: ToolResult) -> str:
        if not result.success:
            return f"{result.tool_name} failed: {result.error_type or 'UNKNOWN_ERROR'}"
        if result.tool_name == "read_file":
            return (
                f"Read {result.data.get('path', '?')} lines "
                f"{result.data.get('start_line', '?')}-{result.data.get('end_line', '?')}"
            )
        if result.tool_name == "search_code":
            return (
                f"Searched {result.data.get('query', '?')!r}: "
                f"{len(result.data.get('matches', []))} matches"
            )
        if result.tool_name == "list_files":
            path = result.data.get("path", ".")
            return f"Listed {path}: {len(result.data.get('files', []))} files"
        return f"Called {result.tool_name}: success"

    def build_messages(self, state: AgentState) -> list[dict[str, Any]]:
        base = self._base_messages(state)
        if not self._exchanges:
            return base

        all_messages = base + [
            message
            for exchange in self._exchanges
            for message in self._exchange_messages(exchange)
        ]
        if self.context_chars(all_messages) <= self.max_context_chars:
            return all_messages

        selected_indices = {len(self._exchanges) - 1}
        selected_tool_count = len(self._exchanges[-1].results)
        for index in range(len(self._exchanges) - 2, -1, -1):
            exchange = self._exchanges[index]
            if selected_tool_count + len(exchange.results) > self.recent_tool_results:
                break
            candidate_indices = selected_indices | {index}
            candidate = base + [
                message
                for selected_index in sorted(candidate_indices)
                for message in self._exchange_messages(self._exchanges[selected_index])
            ]
            if self.context_chars(candidate) > self.max_context_chars:
                break
            selected_indices = candidate_indices
            selected_tool_count += len(exchange.results)

        selected_messages = [
            message
            for index in sorted(selected_indices)
            for message in self._exchange_messages(self._exchanges[index])
        ]
        summary_lines = [
            self._result_summary(result)
            for index, exchange in enumerate(self._exchanges)
            if index not in selected_indices
            for result in exchange.results
        ]
        if not summary_lines:
            return base + selected_messages

        header = "Earlier tool activity:\n"
        kept_lines = []
        for line in reversed(summary_lines):
            candidate_lines = [line, *kept_lines]
            candidate_summary = {
                "role": "system",
                "content": header + "\n".join(candidate_lines),
            }
            if (
                self.context_chars(base + [candidate_summary] + selected_messages)
                > self.max_context_chars
            ):
                break
            kept_lines = candidate_lines
        if not kept_lines:
            return base + selected_messages
        summary = {"role": "system", "content": header + "\n".join(kept_lines)}
        return base + [summary] + selected_messages
