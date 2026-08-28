"""Tool provider interface consumed by the ReAct loop."""

from __future__ import annotations

from abc import ABC, abstractmethod

from evodev.tools.contracts import ToolCall, ToolResult, ToolSpec


class ToolProvider(ABC):
    """Discover and invoke tools without exposing provider-specific objects."""

    @abstractmethod
    def list_tools(self) -> list[ToolSpec]:
        """Return the currently available tools."""

    @abstractmethod
    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        """Validate and execute one tool call."""
