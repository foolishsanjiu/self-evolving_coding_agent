import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from evodev.evaluation import FailureType
from evodev.policy.aggregation import aggregate_failure_patterns
from evodev.policy.models import (
    FROZEN_INVARIANTS,
    FrozenInvariants,
    MutationEvidence,
    PolicyMutation,
    PolicyValidationResult,
    TrainRunEvidence,
    VersionedPolicy,
)
from evodev.policy.runtime import AgentPolicy, InspectTestsMode
from evodev.policy.versioning import PolicyRepository


@pytest.fixture
def policy_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"policy_{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def _mutation(
    *,
    mutation_id: str = "mutation-001",
    parent: str = "policy-v001",
    field: str = "inspect_tests_before_edit",
    old_value: str | bool | int = "off",
    new_value: str | bool | int = "prefer",
) -> PolicyMutation:
    return PolicyMutation(
        mutation_id=mutation_id,
        parent_policy_id=parent,
        field=field,
        old_value=old_value,
        new_value=new_value,
        evidence=[
            MutationEvidence(
                run_ids=["train-run-001"],
                reference="failure-patterns/train-v001.json",
            )
        ],
        hypothesis="Earlier test inspection may reduce incorrect patches.",
        expected_effect="Fewer target-test failures.",
        possible_risk="One extra read may increase token usage.",
    )


def test_agent_policy_has_exact_constrained_search_space() -> None:
    assert set(AgentPolicy.model_fields) == {
        "inspect_tests_before_edit",
        "prefer_search_before_read",
        "max_react_steps",
    }
    assert AgentPolicy().model_dump(mode="json") == {
        "inspect_tests_before_edit": "off",
        "prefer_search_before_read": False,
        "max_react_steps": 15,
    }
    with pytest.raises(ValidationError):
        AgentPolicy(max_react_steps=12)
    with pytest.raises(ValidationError):
        AgentPolicy(context_budget=1000)


def test_frozen_invariants_cannot_be_disabled_or_added_to_mutation_space() -> None:
    assert all(FROZEN_INVARIANTS.model_dump().values())
    with pytest.raises(ValidationError):
        FrozenInvariants(workspace_boundary=False)
    with pytest.raises(ValidationError):
        _mutation(field="workspace_boundary", old_value=True, new_value=False)


def test_mutation_requires_train_evidence_and_strict_value_types() -> None:
    with pytest.raises(ValidationError):
        MutationEvidence(
            split="validation",
            run_ids=["validation-run"],
            reference="validation.json",
        )
    with pytest.raises(ValidationError):
        _mutation(
            field="prefer_search_before_read",
            old_value=0,
            new_value=1,
        )


def test_versioned_policy_detects_hash_tampering() -> None:
    record = VersionedPolicy.create(
        policy_id="policy-v001",
        policy=AgentPolicy(),
        parent_id=None,
        status="accepted",
        mutation=None,
        validation_result=PolicyValidationResult(
            decision="accepted", reason="Initial baseline."
        ),
    )
    payload = record.model_dump(mode="json")
    payload["policy"]["max_react_steps"] = 20

    with pytest.raises(ValidationError, match="content_hash"):
        VersionedPolicy.model_validate(payload)


def test_failure_aggregation_uses_only_learnable_train_failures() -> None:
    runs = [
        TrainRunEvidence(
            run_id="run-b",
            failure_type=FailureType.TARGET_TEST_FAILED,
            inspected_tests_before_edit=False,
            patch_attempts=2,
        ),
        TrainRunEvidence(
            run_id="run-a",
            failure_type=FailureType.TARGET_TEST_FAILED,
            inspected_tests_before_edit=True,
            patch_attempts=4,
        ),
        TrainRunEvidence(
            run_id="run-env",
            failure_type=FailureType.ENVIRONMENT_ERROR,
            inspected_tests_before_edit=False,
            patch_attempts=0,
        ),
        TrainRunEvidence(
            run_id="run-ok",
            failure_type=FailureType.RESOLVED,
            inspected_tests_before_edit=True,
            patch_attempts=1,
        ),
    ]

    patterns = aggregate_failure_patterns(runs)

    assert len(patterns) == 1
    assert patterns[0].failure_type == FailureType.TARGET_TEST_FAILED
    assert patterns[0].failed_runs == 2
    assert patterns[0].edited_before_tests == 1
    assert patterns[0].avg_patch_attempts == 3
    assert patterns[0].run_ids == ["run-a", "run-b"]


def test_repository_preserves_candidate_decisions_and_version_chain(
    policy_root: Path,
) -> None:
    repository = PolicyRepository(policy_root / "policies")
    initial = repository.initialize(AgentPolicy())
    candidate = repository.save_candidate(_mutation())

    changed_fields = {
        field
        for field in AgentPolicy.model_fields
        if getattr(candidate.policy, field) != getattr(initial.policy, field)
    }
    assert changed_fields == {"inspect_tests_before_edit"}
    assert candidate.parent_id == "policy-v001"
    assert candidate.mutation_id == "mutation-001"

    accepted = repository.decide_candidate(
        candidate.policy_id,
        PolicyValidationResult(
            decision="accepted",
            report_path="reports/validation/candidate-001.json",
            reason="External validation gate accepted this candidate.",
        ),
    )
    assert accepted is not None
    assert accepted.policy_id == "policy-v002"
    assert repository.load_index().model_dump() == {
        "champion": "policy-v002",
        "previous_champion": "policy-v001",
    }

    rejected_candidate = repository.save_candidate(
        _mutation(
            mutation_id="mutation-002",
            parent="policy-v002",
            field="inspect_tests_before_edit",
            old_value="prefer",
            new_value="require",
        )
    )
    result = repository.decide_candidate(
        rejected_candidate.policy_id,
        PolicyValidationResult(
            decision="rejected",
            reason="External validation gate rejected this candidate.",
        ),
    )
    assert result is None
    assert repository.load(rejected_candidate.policy_id).status == "rejected"
    assert repository.champion().policy_id == "policy-v002"

    restored = repository.rollback_champion(
        PolicyValidationResult(
            decision="rolled_back",
            report_path="reports/test/policy-v002.json",
            reason="Explicit rollback after final evaluation.",
        )
    )
    assert restored.policy_id == "policy-v001"
    assert repository.load("policy-v002").status == "rolled_back"
    assert repository.load_index().champion == "policy-v001"


def test_policy_hash_is_canonical() -> None:
    first = AgentPolicy(
        inspect_tests_before_edit=InspectTestsMode.PREFER,
        prefer_search_before_read=True,
        max_react_steps=20,
    )
    second = AgentPolicy.model_validate(first.model_dump(mode="json"))

    assert first.content_hash() == second.content_hash()


def test_tracked_champion_policy_snapshot_is_loadable() -> None:
    record = PolicyRepository(Path("policies")).champion()
    expected = AgentPolicy(max_react_steps=10)

    assert record.policy_id == "policy-v003"
    assert record.parent_id == "policy-v002"
    assert record.policy == expected
    assert record.content_hash == expected.content_hash()
