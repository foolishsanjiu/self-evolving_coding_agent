"""Structured reflection and reusable experience schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evodev.benchmark.models import TaskCategory
from evodev.evaluation import FailureType
from evodev.trajectory.models import utc_now


class EvidenceKind(StrEnum):
    TRAJECTORY_EVENT = "trajectory_event"
    BEHAVIORAL_FEATURE = "behavioral_feature"
    EVALUATOR_RESULT = "evaluator_result"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    reference: str = Field(min_length=1)


class Reflection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reflection_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    failure_type: FailureType
    evidence: list[EvidenceReference] = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    bad_strategy: str = Field(min_length=1)
    better_strategy: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    created_at: str = Field(default_factory=utc_now)


class ReflectionDraft(BaseModel):
    """Model-generated reflection fields; identity comes from trusted context."""

    model_config = ConfigDict(extra="forbid")

    failure_type: FailureType
    evidence: list[EvidenceReference] = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    bad_strategy: str = Field(min_length=1)
    better_strategy: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExperienceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_types: list[TaskCategory] = Field(min_length=1)
    trigger: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class StructuredReflection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reflection: Reflection
    experience_candidate: ExperienceCandidate


class StructuredReflectionDraft(BaseModel):
    """Exact JSON contract returned by the single reflection call."""

    model_config = ConfigDict(extra="forbid")

    reflection: ReflectionDraft
    experience_candidate: ExperienceCandidate


class ReflectionContext(BaseModel):
    """Bounded evidence supplied to one reflection call instead of a raw trace."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    run_id: str
    task_description: str
    task_type: TaskCategory
    evaluation_failure: FailureType
    final_patch_summary: str
    relevant_test_failure: str
    behavioral_features: dict[str, bool | int]
    important_events: list[dict[str, object]]
    allowed_evidence_references: list[str]


class ExperienceStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class StoredExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience_id: str
    task_types: list[TaskCategory]
    trigger: str
    recommendation: str
    rationale: str
    keywords: list[str]
    confidence: float
    status: ExperienceStatus
    created_at: str
    updated_at: str


MemorySplit = Literal["train", "validation", "test"]
