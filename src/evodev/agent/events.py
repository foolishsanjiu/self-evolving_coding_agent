"""Lightweight event hook reserved for later trajectory persistence."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentEvent(BaseModel):
    """One observable event emitted by the ReAct loop."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class EventSink(Protocol):
    def emit(self, event: AgentEvent) -> None:
        """Consume one agent event."""


class NoOpEventSink:
    """Default sink used before Task 7 adds trajectory persistence."""

    def emit(self, event: AgentEvent) -> None:
        del event
