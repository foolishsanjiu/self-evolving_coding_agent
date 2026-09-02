"""Structured reflection and reusable experience schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


BehaviorFeature = Literal[
    "searched_before_edit",
    "inspected_tests_before_edit",
    "unique_files_read",
    "patch_attempts",
    "test_runs",
]


class BehaviorTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: BehaviorFeature
    operator: Literal["eq", "gte", "lte"]
    value: bool | int

    @model_validator(mode="after")
    def validate_feature_value(self) -> BehaviorTarget:
        boolean_features = {"searched_before_edit", "inspected_tests_before_edit"}
        if self.feature in boolean_features:
            if self.operator != "eq" or type(self.value) is not bool:
                raise ValueError("Boolean trace targets require eq with a boolean value")
        elif type(self.value) is not int:
            raise ValueError("Numeric trace targets require an integer value")
        return self


class ExperienceExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspect: list[str] = Field(min_length=1, max_length=3)
    act: list[str] = Field(min_length=1, max_length=3)
    verify: list[str] = Field(min_length=1, max_length=3)
    behavior_targets: list[BehaviorTarget] = Field(min_length=1, max_length=5)


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
    execution_contract: ExperienceExecutionContract | None = None


class ExperienceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience_id: str
    reflection_id: str
    task_id: str
    run_id: str
    trajectory_path: str
    evaluation_report_path: str


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_description: str
    task_type: TaskCategory
    keywords: list[str]
    repository_context: str


class ScoredExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience: StoredExperience
    task_type_match: float = Field(ge=0, le=1)
    keyword_overlap: float = Field(ge=0, le=1)
    trigger_match: float = Field(ge=0, le=1)
    confidence_weight: float = Field(ge=0, le=1)
    score: float = Field(ge=0)
    behavior_targets: list[str] = Field(default_factory=list)
    execution_targets: list[BehaviorTarget] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: RetrievalQuery
    mode: Literal["disabled", "relevant", "random"]
    selected: list[ScoredExperience]
    prompt_section: str
    prompt_chars: int = Field(ge=0)
    hit: bool


class ExperienceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^experience-v[0-9]{3}$")
    experiences: list[StoredExperience]
    sources: list[ExperienceSource]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


MemorySplit = Literal["train", "validation", "test"]
