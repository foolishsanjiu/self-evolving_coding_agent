"""Independent evaluation and controlled experiment schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evodev.trajectory.models import utc_now

EVALUATOR_VERSION = "1.0"


class FailureType(StrEnum):
    RESOLVED = "RESOLVED"
    NO_PATCH = "NO_PATCH"
    PATCH_APPLY_FAILED = "PATCH_APPLY_FAILED"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TARGET_TEST_FAILED = "TARGET_TEST_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    AGENT_MAX_STEPS = "AGENT_MAX_STEPS"
    AGENT_TOOL_FAILURE = "AGENT_TOOL_FAILURE"
    AGENT_ERROR = "AGENT_ERROR"
    EVALUATION_TIMEOUT = "EVALUATION_TIMEOUT"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"


class EvaluationRequest(BaseModel):
    """The only Agent-produced inputs accepted by the evaluator."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    final_patch: str
    agent_run_id: str = Field(min_length=1)


class EvaluationGrades(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_exists: bool = False
    patch_applies: bool = False
    syntax_valid: bool = False
    target_tests_pass: bool = False
    regression_tests_pass: bool = False


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_run_id: str
    evaluator_version: Literal["1.0"] = EVALUATOR_VERSION
    benchmark_version: str
    benchmark_hash: str
    grades: EvaluationGrades
    failure_type: FailureType
    resolved: bool
    valid_evaluation: bool
    started_at: str
    finished_at: str = Field(default_factory=utc_now)
    duration_ms: int = Field(ge=0)
    stage_outputs: dict[str, str] = Field(default_factory=dict)


class TrajectoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    react_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    searched_before_edit: bool
    inspected_tests_before_edit: bool
    patch_attempts: int = Field(ge=0)


class ExperimentManifest(BaseModel):
    """All conditions that must remain fixed in a controlled comparison."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1)
    experiment_version: str = Field(min_length=1)
    repetitions: int = Field(gt=0)
    agent_release: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    experience_version: str = Field(min_length=1)
    experience_hash: str = Field(min_length=1)
    experience_mode: Literal["disabled", "relevant", "random"] = "disabled"
    experience_top_k: int = Field(default=0, ge=0, le=3)
    experience_max_chars: int = Field(default=0, ge=0, le=3_000)
    experience_random_seed: int = 0
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    prompt_version: str = Field(min_length=1)
    max_steps: int = Field(gt=0)
    context_budget: int = Field(gt=0)
    tool_provider: str = Field(min_length=1)
    tool_catalog_hash: str = Field(min_length=1)
    sandbox_image: str = Field(min_length=1)
    sandbox_digest: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    benchmark_hash: str = Field(min_length=1)
    benchmark_splits: list[Literal["train", "validation", "test"]] = Field(
        default_factory=lambda: ["train", "validation", "test"]
    )
    evaluator_version: Literal["1.0"] = EVALUATOR_VERSION
    created_at: str = Field(default_factory=utc_now)


class ExperimentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    total_attempts: int = Field(ge=0)
    valid_evaluated_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    resolution_rate: float = Field(ge=0, le=1)
    average_react_steps: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_tokens: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    search_before_edit_rate: float = Field(ge=0, le=1)
    test_inspection_before_edit_rate: float = Field(ge=0, le=1)
    average_patch_attempts: float = Field(ge=0)
    failure_distribution: dict[FailureType, int]
