from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from evodev.config import EvolutionSettings
from evodev.evaluation import FailureType
from evodev.evaluation.models import (
    EvaluationGrades,
    EvaluationResult,
    ExperimentManifest,
)
from evodev.evolution import (
    compare_pairwise_validation,
    evolution_stop_condition,
    finalize_candidate,
    propose_mutation,
    run_smoke_gate,
    validate_policy_schema,
)
from evodev.evolution.cli import _require_paid_confirmation
from evodev.evolution.evidence import aggregate_train_failure_report
from evodev.evolution.models import (
    CandidateGateBundle,
    EvolutionProgress,
    GateDecision,
    PolicyArmMetrics,
    ProposalAttemptReport,
    SchemaGateReport,
    SmokeGateReport,
)
from evodev.evolution.proposal import PROPOSAL_SYSTEM_PROMPT, ProposalRejectedError
from evodev.evolution.validation import controlled_policy_conditions_match
from evodev.llm import FakeLLM, ModelTurn
from evodev.policy.models import (
    FailurePattern,
    MutationEvidence,
    PolicyMutation,
    VersionedPolicy,
)
from evodev.policy.runtime import AgentPolicy
from evodev.policy.versioning import PolicyRepository


@pytest.fixture
def policy_repository() -> Iterator[PolicyRepository]:
    path = Path(".test_runtime") / f"evolution_{uuid4().hex}"
    repository = PolicyRepository(path / "policies")
    repository.initialize(AgentPolicy())
    yield repository
    shutil.rmtree(path)


def _pattern(failed_runs: int = 3) -> FailurePattern:
    return FailurePattern(
        failure_type=FailureType.TARGET_TEST_FAILED,
        failed_runs=failed_runs,
        edited_before_tests=failed_runs,
        avg_patch_attempts=3,
        run_ids=[f"train/run-{index}" for index in range(failed_runs)],
    )


def _draft(field: str = "inspect_tests_before_edit", new_value="require") -> str:
    return json.dumps(
        {
            "field": field,
            "new_value": new_value,
            "hypothesis": "Inspecting tests first may reduce target-test failures.",
            "expected_effect": "Fewer invalid patches.",
            "possible_risk": "An additional read may increase tokens.",
        }
    )


def _candidate(
    repository: PolicyRepository,
    *,
    new_value: str = "require",
) -> VersionedPolicy:
    mutation = PolicyMutation(
        mutation_id=repository.next_mutation_id(),
        parent_policy_id=repository.champion().policy_id,
        field="inspect_tests_before_edit",
        old_value="off",
        new_value=new_value,
        evidence=[
            MutationEvidence(
                run_ids=["train/run-1", "train/run-2"],
                reference="failure-patterns/train-v001.json#TARGET_TEST_FAILED",
            )
        ],
        hypothesis="Inspect tests before editing.",
        expected_effect="Reduce failed patches.",
        possible_risk="Increase read cost.",
    )
    return repository.save_candidate(mutation)


def _arm(
    policy_id: str,
    *,
    resolved: int,
    task_resolutions: dict[str, int] | None = None,
    total: int = 9,
    valid: int = 9,
    tokens: float = 1000,
    steps: float = 10,
    tools: float = 12,
    latency: float = 1000,
) -> PolicyArmMetrics:
    return PolicyArmMetrics(
        policy_id=policy_id,
        total_attempts=total,
        valid_attempts=valid,
        resolved_attempts=resolved,
        resolution_rate=resolved / valid if valid else 0,
        average_tokens=tokens,
        average_react_steps=steps,
        average_tool_calls=tools,
        average_latency_ms=latency,
        task_resolutions=task_resolutions
        or {"task_007": 2, "task_008": 1, "task_009": 2},
    )


def test_proposal_binds_trusted_parent_old_value_and_train_evidence(
    policy_repository: PolicyRepository,
) -> None:
    model = FakeLLM([ModelTurn(content=_draft())])

    proposal = propose_mutation(
        model,
        policy_repository.champion(),
        [_pattern()],
        mutation_id="mutation-001",
        evidence_reference="failure-patterns/train-v001.json",
    )
    mutation = proposal.mutation

    assert mutation.parent_policy_id == "policy-v001"
    assert mutation.old_value == "off"
    assert mutation.new_value == "require"
    assert all(item.split == "train" for item in mutation.evidence)
    assert '"split"' not in model.requests[0][0][1]["content"]
    assert model.requests[0][1] == []
    assert '"off", "prefer", or "require"' in PROPOSAL_SYSTEM_PROMPT


def test_proposal_requires_repeated_pattern_and_rejects_duplicate_transition(
    policy_repository: PolicyRepository,
) -> None:
    no_call_model = FakeLLM([])
    with pytest.raises(ValueError, match="No repeated"):
        propose_mutation(
            no_call_model,
            policy_repository.champion(),
            [_pattern(1)],
            mutation_id="mutation-001",
            evidence_reference="train.json",
        )
    assert no_call_model.requests == []

    with pytest.raises(ValueError, match="already attempted"):
        propose_mutation(
            FakeLLM([ModelTurn(content=_draft())]),
            policy_repository.champion(),
            [_pattern()],
            mutation_id="mutation-001",
            evidence_reference="train.json",
            attempted_mutations={
                ("inspect_tests_before_edit", "off", "require")
            },
        )


def test_invalid_proposal_is_auditable_rejection(
    policy_repository: PolicyRepository,
) -> None:
    turn = ModelTurn(
        content=_draft(new_value="enabled"),
        input_tokens=100,
        output_tokens=20,
    )

    with pytest.raises(ProposalRejectedError) as captured:
        propose_mutation(
            FakeLLM([turn]),
            policy_repository.champion(),
            [_pattern()],
            mutation_id="mutation-001",
            evidence_reference="train.json",
        )

    assert captured.value.draft.new_value == "enabled"
    assert captured.value.turn.input_tokens == 100


def test_schema_and_smoke_gates_enforce_candidate_boundary(
    policy_repository: PolicyRepository,
) -> None:
    candidate = _candidate(policy_repository)

    schema = validate_policy_schema(policy_repository.champion(), candidate)
    smoke = run_smoke_gate(candidate, Path.cwd())

    assert schema.passed is True
    assert all(schema.checks.values())
    assert smoke.passed is True
    assert smoke.agent_status == "SUCCESS"
    assert smoke.policy_precondition_failures == 1

    stale = candidate.model_copy(update={"parent_id": "policy-v999"})
    failed = validate_policy_schema(policy_repository.champion(), stale)
    assert failed.passed is False
    assert failed.checks["parent_is_champion"] is False


def test_resolution_improvement_accepts_and_decline_rejects() -> None:
    champion = _arm("policy-v001", resolved=5)
    better = _arm("candidate-001", resolved=6)
    worse = _arm(
        "candidate-002",
        resolved=4,
        tokens=500,
        steps=5,
        tools=6,
        latency=500,
    )

    accepted = compare_pairwise_validation(
        champion,
        better,
        candidate_id="candidate-001",
        controlled_conditions_match=True,
    )
    rejected = compare_pairwise_validation(
        champion,
        worse,
        candidate_id="candidate-002",
        controlled_conditions_match=True,
    )

    assert accepted.decision == GateDecision.ACCEPT
    assert rejected.decision == GateDecision.REJECT
    assert "efficiency cannot override" in rejected.reason


def test_catastrophic_regression_overrides_aggregate_gain() -> None:
    champion = _arm(
        "policy-v001",
        resolved=5,
        task_resolutions={"task_007": 2, "task_008": 1, "task_009": 2},
    )
    candidate = _arm(
        "candidate-001",
        resolved=6,
        task_resolutions={"task_007": 0, "task_008": 3, "task_009": 3},
    )

    report = compare_pairwise_validation(
        champion,
        candidate,
        candidate_id="candidate-001",
        controlled_conditions_match=True,
    )

    assert report.decision == GateDecision.REJECT
    assert report.catastrophic_regressions == ["task_007"]


def test_tied_resolution_requires_tokens_and_supporting_cost_reduction() -> None:
    champion = _arm("policy-v001", resolved=5)
    efficient = _arm(
        "candidate-001",
        resolved=5,
        tokens=800,
        steps=8,
        tools=12,
        latency=1000,
    )
    token_only = _arm(
        "candidate-002",
        resolved=5,
        tokens=800,
        steps=10,
        tools=12,
        latency=1000,
    )

    accepted = compare_pairwise_validation(
        champion,
        efficient,
        candidate_id="candidate-001",
        controlled_conditions_match=True,
    )
    rejected = compare_pairwise_validation(
        champion,
        token_only,
        candidate_id="candidate-002",
        controlled_conditions_match=True,
    )

    assert accepted.decision == GateDecision.ACCEPT
    assert rejected.decision == GateDecision.REJECT


def test_incomplete_or_uncontrolled_pairwise_is_inconclusive() -> None:
    report = compare_pairwise_validation(
        _arm("policy-v001", resolved=4),
        _arm("candidate-001", resolved=4, total=8, valid=8),
        candidate_id="candidate-001",
        controlled_conditions_match=False,
    )

    assert report.decision == GateDecision.INCONCLUSIVE


@pytest.mark.parametrize(
    ("progress", "has_pattern", "all_attempted", "reason"),
    [
        (EvolutionProgress(api_budget_exhausted=True), True, False, "budget"),
        (EvolutionProgress(generation=6), True, False, "generations"),
        (EvolutionProgress(generations_without_improvement=2), True, False, "patience"),
        (EvolutionProgress(), False, False, "failure pattern"),
        (EvolutionProgress(), True, True, "single-field"),
        (EvolutionProgress(candidates_in_generation=2), True, False, "Candidate budget"),
    ],
)
def test_evolution_stop_conditions_are_explicit(
    progress: EvolutionProgress,
    has_pattern: bool,
    all_attempted: bool,
    reason: str,
) -> None:
    result = evolution_stop_condition(
        progress,
        EvolutionSettings(),
        has_repeated_failure_pattern=has_pattern,
        all_single_field_mutations_attempted=all_attempted,
    )

    assert result.should_stop is True
    assert reason.lower() in result.reason.lower()


def test_evolution_continues_within_all_budgets() -> None:
    result = evolution_stop_condition(
        EvolutionProgress(),
        EvolutionSettings(),
        has_repeated_failure_pattern=True,
        all_single_field_mutations_attempted=False,
    )

    assert result.should_stop is False
    assert result.reason is None


def test_finalize_candidate_promotes_only_after_all_gates(
    policy_repository: PolicyRepository,
) -> None:
    candidate = _candidate(policy_repository)
    schema = validate_policy_schema(policy_repository.champion(), candidate)
    smoke = SmokeGateReport(
        candidate_id=candidate.policy_id,
        passed=True,
        fixture="fixtures/simple_read",
        agent_status="SUCCESS",
        react_steps=3,
        tool_calls=2,
        policy_precondition_failures=1,
        reason="passed",
    )
    pairwise = compare_pairwise_validation(
        _arm("policy-v001", resolved=5),
        _arm(candidate.policy_id, resolved=6),
        candidate_id=candidate.policy_id,
        controlled_conditions_match=True,
    )

    promoted = finalize_candidate(
        policy_repository,
        CandidateGateBundle(
            candidate_id=candidate.policy_id,
            schema_gate=schema,
            smoke_gate=smoke,
            pairwise_gate=pairwise,
        ),
        report_path="evolution_runs/evo-001/candidate-001/gates.json",
    )

    assert promoted is not None
    assert promoted.policy_id == "policy-v002"
    assert policy_repository.load("policy-v001").status == "accepted"
    assert policy_repository.champion().policy_id == "policy-v002"


def test_failed_schema_rejects_without_pairwise_run(
    policy_repository: PolicyRepository,
) -> None:
    candidate = _candidate(policy_repository)
    schema = SchemaGateReport(
        candidate_id=candidate.policy_id,
        passed=False,
        checks={"frozen_invariants_intact": False},
        reason="Frozen invariant changed.",
    )

    result = finalize_candidate(
        policy_repository,
        CandidateGateBundle(candidate_id=candidate.policy_id, schema_gate=schema),
        report_path="evolution_runs/evo-001/candidate-001/gates.json",
    )

    assert result is None
    assert policy_repository.load(candidate.policy_id).status == "rejected"


def test_inconclusive_validation_keeps_candidate_pending(
    policy_repository: PolicyRepository,
) -> None:
    candidate = _candidate(policy_repository)
    schema = validate_policy_schema(policy_repository.champion(), candidate)
    smoke = SmokeGateReport(
        candidate_id=candidate.policy_id,
        passed=True,
        fixture="fixtures/simple_read",
        agent_status="SUCCESS",
        react_steps=3,
        tool_calls=2,
        policy_precondition_failures=1,
        reason="passed",
    )
    pairwise = compare_pairwise_validation(
        _arm("policy-v001", resolved=4),
        _arm(candidate.policy_id, resolved=4, total=8, valid=8),
        candidate_id=candidate.policy_id,
        controlled_conditions_match=True,
    )

    result = finalize_candidate(
        policy_repository,
        CandidateGateBundle(
            candidate_id=candidate.policy_id,
            schema_gate=schema,
            smoke_gate=smoke,
            pairwise_gate=pairwise,
        ),
        report_path="evolution_runs/evo-001/candidate-001/gates.json",
    )

    assert result is None
    assert policy_repository.load(candidate.policy_id).status == "candidate"


def _manifest(policy_id: str, policy_hash: str, max_steps: int = 15) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id=f"experiment-{policy_id}",
        experiment_version="policy-gate-v1",
        repetitions=3,
        agent_release="0.1.0",
        policy_version=policy_id,
        policy_hash=policy_hash,
        experience_version="none",
        experience_hash="none",
        model="fixed-model",
        temperature=0.1,
        prompt_version="react-system-v1+policy-v1",
        max_steps=max_steps,
        context_budget=60_000,
        tool_provider="mcp-devtools-v1",
        tool_catalog_hash="catalog-hash",
        sandbox_image="evodev-python:3.11",
        sandbox_digest="sha256:image",
        benchmark_version="1.0",
        benchmark_hash="benchmark-hash",
        benchmark_splits=["validation"],
    )


def test_controlled_conditions_allow_only_policy_fields() -> None:
    champion = _manifest("policy-v001", "hash-one")
    candidate = _manifest("candidate-001", "hash-two", max_steps=20)

    assert controlled_policy_conditions_match(champion, candidate)
    changed_model = candidate.model_copy(update={"model": "other-model"})
    assert not controlled_policy_conditions_match(champion, changed_model)


def test_paid_cli_stages_require_explicit_confirmation() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        _require_paid_confirmation(False, "Pairwise Validation")
    _require_paid_confirmation(True, "Pairwise Validation")


def test_first_paid_proposal_rejection_is_preserved() -> None:
    report = ProposalAttemptReport.model_validate_json(
        Path("evolution/evolution-v1/proposal-attempt-001.json").read_text(
            encoding="utf-8"
        )
    )

    assert report.status == "rejected"
    assert report.observed_field == "inspect_tests_before_edit"
    assert report.candidate_id is None
    assert report.draft is None


def test_second_paid_proposal_and_pre_validation_gates_are_preserved() -> None:
    proposal = ProposalAttemptReport.model_validate_json(
        Path("evolution/evolution-v1/proposal-attempt-002.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = PolicyRepository(Path("policies")).load("candidate-001")
    gate_data = json.loads(
        Path(
            "evolution/evolution-v1/candidate-001/gates-pre-validation.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal.status == "accepted"
    assert proposal.input_tokens == 409
    assert proposal.output_tokens == 413
    assert proposal.draft is not None
    assert proposal.draft.new_value == "prefer"
    assert candidate.parent_id == "policy-v001"
    assert candidate.policy.inspect_tests_before_edit == "prefer"
    assert gate_data["schema_gate"]["passed"] is True
    assert gate_data["smoke_gate"]["passed"] is True
    assert gate_data["pairwise_gate"] is None


def test_candidate_001_rejected_case_study_is_preserved() -> None:
    candidate = PolicyRepository(Path("policies")).load("candidate-001")
    gates = CandidateGateBundle.model_validate_json(
        Path("evolution/evolution-v1/candidate-001/gates-final.json").read_text(
            encoding="utf-8"
        )
    )

    assert candidate.status == "rejected"
    assert candidate.validation_result.decision == "rejected"
    assert candidate.validation_result.report_path == (
        "evolution/evolution-v1/candidate-001/gates-final.json"
    )
    assert gates.pairwise_gate is not None
    assert gates.pairwise_gate.decision == GateDecision.REJECT
    assert gates.pairwise_gate.controlled_conditions_match is True
    assert gates.pairwise_gate.champion.resolved_attempts == 6
    assert gates.pairwise_gate.candidate.resolved_attempts == 4
    assert gates.pairwise_gate.catastrophic_regressions == []


def test_third_paid_proposal_and_candidate_002_are_preserved() -> None:
    proposal = ProposalAttemptReport.model_validate_json(
        Path("evolution/evolution-v1/proposal-attempt-003.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = PolicyRepository(Path("policies")).load("candidate-002")
    gates = CandidateGateBundle.model_validate_json(
        Path(
            "evolution/evolution-v1/candidate-002/gates-pre-validation.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal.status == "accepted"
    assert proposal.input_tokens == 435
    assert proposal.output_tokens == 923
    assert proposal.draft is not None
    assert proposal.draft.new_value == "require"
    assert candidate.parent_id == "policy-v001"
    assert candidate.status == "candidate"
    assert candidate.policy.inspect_tests_before_edit == "require"
    assert gates.schema_gate.passed is True
    assert gates.smoke_gate is not None
    assert gates.smoke_gate.passed is True
    assert gates.smoke_gate.policy_precondition_failures == 1
    assert gates.pairwise_gate is None


def _evaluation(task_id: str, run_id: str) -> EvaluationResult:
    return EvaluationResult(
        task_id=task_id,
        agent_run_id=run_id,
        benchmark_version="1.0",
        benchmark_hash="benchmark-hash",
        grades=EvaluationGrades(patch_exists=True, patch_applies=True, syntax_valid=True),
        failure_type=FailureType.TARGET_TEST_FAILED,
        resolved=False,
        valid_evaluation=True,
        started_at="2026-08-30T00:00:00+00:00",
        duration_ms=1,
    )


def test_failure_report_excludes_validation_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(".test_runtime") / f"evidence_{uuid4().hex}"
    experiment_id = "train-history"
    try:
        for task_id, run_id, attempt in [
            ("task_001", "train-1", "attempt_01"),
            ("task_001", "train-2", "attempt_02"),
            ("task_007", "validation-1", "attempt_03"),
        ]:
            report_path = (
                path
                / "evaluation_runs"
                / experiment_id
                / "instances"
                / task_id
                / attempt
                / "report.json"
            )
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                _evaluation(task_id, run_id).model_dump_json(indent=2), encoding="utf-8"
            )
            run_path = path / "runs" / experiment_id / run_id
            run_path.mkdir(parents=True)
            (run_path / "trace_features.json").write_text(
                json.dumps(
                    {
                        "inspected_tests_before_edit": False,
                        "patch_attempts": 3,
                    }
                ),
                encoding="utf-8",
            )

        class FakeLoader:
            def __init__(self, root: Path) -> None:
                self.root = root

            def load_tasks(self):
                return [
                    SimpleNamespace(
                        split="train", config=SimpleNamespace(task_id="task_001")
                    ),
                    SimpleNamespace(
                        split="validation", config=SimpleNamespace(task_id="task_007")
                    ),
                ]

        monkeypatch.setattr("evodev.evolution.evidence.BenchmarkLoader", FakeLoader)
        report = aggregate_train_failure_report(
            path,
            [experiment_id],
            report_id="failure-patterns-v001",
        )

        assert report.split == "train"
        assert report.patterns[0].failed_runs == 2
        assert report.patterns[0].run_ids == [
            "train-history/train-1",
            "train-history/train-2",
        ]
        assert "validation-1" not in report.model_dump_json()
    finally:
        if path.exists():
            shutil.rmtree(path)
