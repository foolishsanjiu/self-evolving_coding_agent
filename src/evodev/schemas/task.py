"""Task schemas shared by interactive and benchmark runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskSpec(BaseModel):
    """Canonical description of one coding task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    workspace_path: Path
    metadata: dict[str, Any] = Field(default_factory=dict)
