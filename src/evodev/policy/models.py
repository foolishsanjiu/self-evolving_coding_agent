"""Typed, constrained policy and versioning schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evodev.evaluation import FailureType
from evodev.policy.runtime import AgentPolicy
from evodev.trajectory.models import utc_now


class FrozenInvariants(BaseModel):
    """Safety envelope deliberately excluded from the evolvable AgentPolicy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_boundary: Literal[True] = True
    docker_sandbox_required: Literal[True] = True
    arbitrary_shell_forbidden: Literal[True] = True
    network_disabled_by_default: Literal[True] = True
    hidden_test_isolation: Literal[True] = True
    split_rules_enforced: Literal[True] = True
    secret_redaction: Literal[True] = True
    evaluator_logic_frozen: Literal[True] = True
    original_repository_protected: Literal[True] = True
    docker_security_limits_enforced: Literal[True] = True
    mcp_permission_boundary: Literal[True] = True


FROZEN_INVARIANTS = FrozenInvariants()


class MutationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: Literal["train"] = "train"
    run_ids: list[str] = Field(min_length=1)
    reference: str = Field(min_length=1)


PolicyField = Literal[
    "inspect_tests_before_edit",
    "prefer_search_before_read",
    "max_react_steps",
]


class PolicyMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mutation_id: str = Field(pattern=r"^mutation-[0-9]{3}$")
    parent_policy_id: str = Field(pattern=r"^policy-v[0-9]{3}$")
    field: PolicyField
    old_value: str | bool | int
    new_value: str | bool | int
    evidence: list[MutationEvidence] = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    possible_risk: str = Field(min_length=1)
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_values(self) -> PolicyMutation:
        allowed: dict[str, set[object]] = {
            "inspect_tests_before_edit": {"off", "prefer", "require"},
            "prefer_search_before_read": {False, True},
            "max_react_steps": {10, 15, 20},
        }
        expected_types = {
            "inspect_tests_before_edit": str,
            "prefer_search_before_read": bool,
            "max_react_steps": int,
        }
        if type(self.old_value) is not expected_types[self.field] or type(
            self.new_value
        ) is not expected_types[self.field]:
            raise ValueError(f"Mutation values have the wrong type for field: {self.field}")
        if (
            self.old_value not in allowed[self.field]
            or self.new_value not in allowed[self.field]
        ):
            raise ValueError(f"Mutation values are invalid for field: {self.field}")
        if self.old_value == self.new_value:
            raise ValueError("Mutation must change exactly one field value")
        return self


class PolicyStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class PolicyValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["pending", "accepted", "rejected", "rolled_back"]
    report_path: str | None = None
    reason: str = Field(min_length=1)


class VersionedPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(pattern=r"^(?:policy-v|candidate-)[0-9]{3}$")
    parent_id: str | None = Field(default=None, pattern=r"^policy-v[0-9]{3}$")
    status: PolicyStatus
    mutation_id: str | None = Field(default=None, pattern=r"^mutation-[0-9]{3}$")
    mutation: PolicyMutation | None = None
    validation_result: PolicyValidationResult
    policy: AgentPolicy
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def verify_record(self) -> VersionedPolicy:
        if self.content_hash != self.policy.content_hash():
            raise ValueError("Policy content_hash does not match policy contents")
        is_candidate = self.policy_id.startswith("candidate-")
        if is_candidate and self.parent_id is None:
            raise ValueError("Candidate policy requires a parent_id")
        if is_candidate and self.mutation is None:
            raise ValueError("Candidate policy requires one mutation")
        expected_mutation_id = self.mutation.mutation_id if self.mutation else None
        if self.mutation_id != expected_mutation_id:
            raise ValueError("Snapshot mutation_id does not match its mutation")
        if self.mutation and self.mutation.parent_policy_id != self.parent_id:
            raise ValueError("Mutation parent does not match snapshot parent")
        if not is_candidate and self.status in {PolicyStatus.CANDIDATE, PolicyStatus.REJECTED}:
            raise ValueError("Versioned policy file has an invalid status")
        return self

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy: AgentPolicy,
        parent_id: str | None,
        status: PolicyStatus,
        mutation: PolicyMutation | None,
        validation_result: PolicyValidationResult,
    ) -> VersionedPolicy:
        return cls(
            policy_id=policy_id,
            parent_id=parent_id,
            status=status,
            mutation_id=mutation.mutation_id if mutation else None,
            mutation=mutation,
            validation_result=validation_result,
            policy=policy,
            content_hash=policy.content_hash(),
        )


class PolicyIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    champion: str = Field(pattern=r"^policy-v[0-9]{3}$")
    previous_champion: str | None = Field(default=None, pattern=r"^policy-v[0-9]{3}$")


class TrainRunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    split: Literal["train"] = "train"
    failure_type: FailureType
    inspected_tests_before_edit: bool
    patch_attempts: int = Field(ge=0)


class FailurePattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_type: FailureType
    failed_runs: int = Field(gt=0)
    edited_before_tests: int = Field(ge=0)
    avg_patch_attempts: float = Field(ge=0)
    run_ids: list[str] = Field(min_length=1)
