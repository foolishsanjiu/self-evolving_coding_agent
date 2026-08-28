"""Provider-neutral model response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from evodev.tools.contracts import ToolCall


class ModelTurn(BaseModel):
    """Provider-neutral result of one model generation."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
