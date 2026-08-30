"""Typed reports and bounded-search state for policy evolution."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evodev.evaluation.models import EvaluationResult, ExperimentManifest, ExperimentSummary
from evodev.policy.models import FailurePattern, PolicyMutation
from evodev.policy.runtime import AgentPolicy
from evodev.trajectory.models import utc_now


class MutationProposalDraft(BaseModel):
    """The only untrusted fields the Proposal LLM may choose."""

    model_config = ConfigDict(extra="forbid", strict=True)

    field: Literal[
        "inspect_tests_before_edit",
        "prefer_search_before_read",
        "max_react_steps",
    ]
    new_value: str | bool | int
    hypothesis: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    possible_risk: str = Field(min_length=1)


class ProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation: PolicyMutation
    draft: MutationProposalDraft
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ProposalAttemptReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(pattern=r"^proposal-attempt-[0-9]{3}$")
    status: Literal["accepted", "rejected"]
    paid_call: Literal[True] = True
    model: str = Field(min_length=1)
    parent_policy_id: str
    pattern_report_path: str
    pattern_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft: MutationProposalDraft | None = None
    observed_field: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    candidate_id: str | None = None
    rejection_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)


class FailurePatternReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    split: Literal["train"] = "train"
    source_experiment_ids: list[str] = Field(min_length=1)
    patterns: list[FailurePattern]
    created_at: str = Field(default_factory=utc_now)


class SchemaGateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    passed: bool
    checks: dict[str, bool]
    reason: str = Field(min_length=1)


class SmokeGateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    passed: bool
    fixture: str
    agent_status: str
    react_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    policy_precondition_failures: int = Field(ge=0)
    reason: str = Field(min_length=1)


class PolicyArmMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    total_attempts: int = Field(gt=0)
    valid_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    resolution_rate: float = Field(ge=0, le=1)
    average_tokens: float = Field(ge=0)
    average_react_steps: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    task_resolutions: dict[str, int]

    @model_validator(mode="after")
    def validate_counts(self) -> PolicyArmMetrics:
        if self.valid_attempts > self.total_attempts:
            raise ValueError("valid_attempts exceeds total_attempts")
        if self.resolved_attempts > self.valid_attempts:
            raise ValueError("resolved_attempts exceeds valid_attempts")
        return self


class GateDecision(StrEnum):
    ACCEPT = "accepted"
    REJECT = "rejected"
    INCONCLUSIVE = "inconclusive"


class PairwiseGateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    decision: GateDecision
    reason: str = Field(min_length=1)
    champion: PolicyArmMetrics
    candidate: PolicyArmMetrics
    controlled_conditions_match: bool
    catastrophic_regressions: list[str] = Field(default_factory=list)
    significant_cost_reduction: float = Field(gt=0, le=0.5)
    created_at: str = Field(default_factory=utc_now)


class PolicyExperimentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    manifest: ExperimentManifest
    summary: ExperimentSummary
    results: list[EvaluationResult]
    trajectory_paths: dict[str, str]


class CandidateGateBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    schema_gate: SchemaGateReport
    smoke_gate: SmokeGateReport | None = None
    pairwise_gate: PairwiseGateReport | None = None
    created_at: str = Field(default_factory=utc_now)


class EvolutionProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation: int = Field(default=1, ge=1)
    candidates_in_generation: int = Field(default=0, ge=0)
    generations_without_improvement: int = Field(default=0, ge=0)
    attempted_mutations: set[tuple[str, str, str]] = Field(default_factory=set)
    api_budget_exhausted: bool = False


class EvolutionStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_stop: bool
    reason: str | None = None
    created_at: str = Field(default_factory=utc_now)


class ProposalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    champion_id: str
    champion_policy: AgentPolicy
    repeated_train_patterns: list[FailurePattern] = Field(min_length=1)
    attempted_mutations: list[tuple[str, str, str]] = Field(default_factory=list)
