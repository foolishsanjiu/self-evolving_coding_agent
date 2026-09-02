"""Versioned schemas for lightweight EvoDev trajectories."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evodev.tools.contracts import ToolSpec

TRAJECTORY_FORMAT_VERSION = "1.0"
PersistedEventType = Literal[
    "RUN_STARTED",
    "MODEL_TURN",
    "TOOL_CALL",
    "TOOL_RESULT",
    "FINAL_ANSWER",
    "RUN_FINISHED",
    "RUN_ERROR",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def tool_catalog_hash(tools: list[ToolSpec]) -> str:
    """Hash a canonical, order-independent snapshot of the tool catalog."""
    payload = [tool.model_dump(mode="json") for tool in sorted(tools, key=lambda item: item.name)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RunMetadata(BaseModel):
    """Complete experimental snapshot written before the first agent step."""

    model_config = ConfigDict(extra="forbid")

    trajectory_format_version: Literal["1.0"] = TRAJECTORY_FORMAT_VERSION
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent_release: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    experience_version: str = Field(min_length=1)
    experience_hash: str = Field(min_length=1)
    experience_consumer: Literal["legacy-v1", "execution-contract-v1"] = "legacy-v1"
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    prompt_version: str = Field(min_length=1)
    max_steps: int = Field(gt=0)
    context_budget: int = Field(gt=0)
    tool_provider: str = Field(min_length=1)
    tool_catalog_hash: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    benchmark_hash: str = Field(min_length=1)
    sandbox_image: str = Field(min_length=1)
    sandbox_digest: str = Field(min_length=1)
    started_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None
    status: str | None = None


class TrajectoryEvent(BaseModel):
    """One append-only, totally ordered public behavior event."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    type: PersistedEventType
    timestamp: str = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class ArtifactReference(BaseModel):
    """Integrity-checked pointer replacing large inline event values."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chars: int = Field(ge=0)
    truncated_for_llm: bool
