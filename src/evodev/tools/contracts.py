"""Canonical tool schemas shared by Agent and tool providers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolSpec(BaseModel):
    """Description and risk metadata for one callable tool."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    source: str = Field(min_length=1)
    read_only: bool
    destructive: bool
    idempotent: bool


class ToolCall(BaseModel):
    """Provider-neutral tool invocation requested by the model."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Human-readable and structured result of one tool invocation."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    success: bool
    content: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    duration_ms: int = Field(ge=0)
