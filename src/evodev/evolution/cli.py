"""Explicit CLI stages for bounded Policy evolution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evodev.config import load_settings
from evodev.evolution.engine import (
    finalize_candidate,
    rollback_last_known_good,
    write_gate_bundle,
)
from evodev.evolution.evidence import (
    aggregate_train_failure_report,
    write_failure_pattern_report,
)
from evodev.evolution.gates import run_smoke_gate, validate_policy_schema
from evodev.evolution.models import (
    CandidateGateBundle,
    FailurePatternReport,
    ProposalAttemptReport,
)
from evodev.evolution.proposal import ProposalRejectedError, propose_mutation
from evodev.evolution.state import (
    evolution_state_path,
    load_or_rebuild_evolution_state,
    proposal_stop_condition,
    record_candidate_decision,
    record_champion_rollback,
    register_candidate,
    remaining_single_field_mutations,
    write_evolution_state,
)
from evodev.evolution.validation import PolicyExperimentRunner, run_pairwise_validation
from evodev.llm import LLMClient
from evodev.policy.versioning import PolicyRepository


def _require_paid_confirmation(confirmed: bool, scope: str) -> None:
    if not confirmed:
        raise PermissionError(
            f"{scope} performs paid model calls; rerun with --confirm-paid after approval"
        )


def _bundle_path(project_root: Path, evolution_id: str, candidate_id: str) -> Path:
    return (
        project_root
        / "evolution_runs"
        / evolution_id
        / candidate_id
        / "gates.json"
    )


def _next_proposal_attempt_path(project_root: Path, evolution_id: str) -> Path:
    numbers = []
    for root in [
        project_root / "evolution" / evolution_id,
        project_root / "evolution_runs" / evolution_id,
    ]:
        for path in root.glob("proposal-attempt-*.json"):
            numbers.append(int(path.stem.removeprefix("proposal-attempt-")))
    attempt_id = f"proposal-attempt-{max(numbers, default=0) + 1:03d}"
    return project_root / "evolution_runs" / evolution_id / f"{attempt_id}.json"


def _write_proposal_attempt(report: ProposalAttemptReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _aggregate(arguments: argparse.Namespace) -> None:
    report = aggregate_train_failure_report(
        arguments.project_root,
        arguments.experiment_ids,
        report_id=arguments.report_id,
    )
    output = arguments.output
    if not output.is_absolute():
        output = arguments.project_root / output
    write_failure_pattern_report(report, output)
    print(report.model_dump_json(indent=2))


def _collect_train(arguments: argparse.Namespace) -> None:
    _require_paid_confirmation(arguments.confirm_paid, "Train collection")
    settings = load_settings(arguments.project_root / "configs", arguments.project_root / ".env")
    policy = PolicyRepository(arguments.project_root / "policies").champion()
    output = PolicyExperimentRunner(
        arguments.project_root,
        settings,
        policy,
        experiment_id=arguments.experiment_id,
        split="train",
        repetitions=arguments.repetitions,
    ).run()
    print(output.summary.model_dump_json(indent=2))


def _propose(arguments: argparse.Namespace) -> None:
    report_path = arguments.pattern_report
    if not report_path.is_absolute():
        report_path = arguments.project_root / report_path
    report = FailurePatternReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    repository = PolicyRepository(arguments.project_root / "policies")
    champion = repository.champion()
    settings = load_settings(arguments.project_root / "configs", arguments.project_root / ".env")
    state = load_or_rebuild_evolution_state(
        arguments.project_root, arguments.evolution_id, settings.evolution
    )
    stop = proposal_stop_condition(
        state,
        settings.evolution,
        champion,
        has_repeated_failure_pattern=any(
            pattern.failed_runs >= 2 for pattern in report.patterns
        ),
    )
    if stop.should_stop:
        raise RuntimeError(f"Evolution stopped: {stop.reason}")
    _require_paid_confirmation(arguments.confirm_paid, "Mutation proposal")
    relative_report_path = report_path.relative_to(arguments.project_root).as_posix()
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    attempt_path = _next_proposal_attempt_path(
        arguments.project_root, arguments.evolution_id
    )
    try:
        proposal = propose_mutation(
            LLMClient(settings.model),
            champion,
            report.patterns,
            mutation_id=repository.next_mutation_id(),
            evidence_reference=relative_report_path,
            attempted_mutations=repository.attempted_mutations(),
        )
    except ProposalRejectedError as exc:
        rejected = ProposalAttemptReport(
            attempt_id=attempt_path.stem,
            status="rejected",
            model=settings.model.model,
            parent_policy_id=champion.policy_id,
            pattern_report_path=relative_report_path,
            pattern_report_hash=report_hash,
            draft=exc.draft,
            observed_field=exc.draft.field,
            input_tokens=exc.turn.input_tokens,
            output_tokens=exc.turn.output_tokens,
            rejection_reason=str(exc),
        )
        _write_proposal_attempt(rejected, attempt_path)
        print(rejected.model_dump_json(indent=2))
        return
    candidate = repository.save_candidate(proposal.mutation)
    state = register_candidate(state, candidate, settings.evolution)
    write_evolution_state(
        state,
        evolution_state_path(arguments.project_root, arguments.evolution_id),
    )
    _write_proposal_attempt(
        ProposalAttemptReport(
            attempt_id=attempt_path.stem,
            status="accepted",
            model=settings.model.model,
            parent_policy_id=champion.policy_id,
            pattern_report_path=relative_report_path,
            pattern_report_hash=report_hash,
            draft=proposal.draft,
            observed_field=proposal.draft.field,
            input_tokens=proposal.input_tokens,
            output_tokens=proposal.output_tokens,
            candidate_id=candidate.policy_id,
        ),
        attempt_path,
    )
    schema = validate_policy_schema(champion, candidate)
    smoke = run_smoke_gate(candidate, arguments.project_root) if schema.passed else None
    bundle = CandidateGateBundle(
        candidate_id=candidate.policy_id,
        schema_gate=schema,
        smoke_gate=smoke,
    )
    path = _bundle_path(arguments.project_root, arguments.evolution_id, candidate.policy_id)
    write_gate_bundle(bundle, path)
    if not schema.passed or smoke is None or not smoke.passed:
        finalize_candidate(
            repository,
            bundle,
            report_path=path.relative_to(arguments.project_root).as_posix(),
        )
        candidate = repository.load(candidate.policy_id)
        state = record_candidate_decision(
            state,
            candidate,
            "rejected",
            settings.evolution,
            champion_id=repository.champion().policy_id,
            completed_at=bundle.created_at,
        )
        write_evolution_state(
            state,
            evolution_state_path(arguments.project_root, arguments.evolution_id),
        )
    print(bundle.model_dump_json(indent=2))


def _validate(arguments: argparse.Namespace) -> None:
    repository = PolicyRepository(arguments.project_root / "policies")
    champion = repository.champion()
    candidate = repository.load(arguments.candidate_id)
    settings = load_settings(
        arguments.project_root / "configs", arguments.project_root / ".env"
    )
    state = load_or_rebuild_evolution_state(
        arguments.project_root, arguments.evolution_id, settings.evolution
    )
    if state.pending_candidate_id != candidate.policy_id:
        raise RuntimeError(
            "Pairwise Validation Candidate is not pending in the current generation"
        )
    _require_paid_confirmation(arguments.confirm_paid, "Pairwise Validation")
    schema = validate_policy_schema(champion, candidate)
    smoke = run_smoke_gate(candidate, arguments.project_root) if schema.passed else None
    pairwise = None
    if schema.passed and smoke and smoke.passed:
        pairwise = run_pairwise_validation(
            arguments.project_root,
            settings,
            champion,
            candidate,
            evolution_id=arguments.evolution_id,
        )
    bundle = CandidateGateBundle(
        candidate_id=candidate.policy_id,
        schema_gate=schema,
        smoke_gate=smoke,
        pairwise_gate=pairwise,
    )
    path = _bundle_path(arguments.project_root, arguments.evolution_id, candidate.policy_id)
    write_gate_bundle(bundle, path)
    promoted = finalize_candidate(
        repository,
        bundle,
        report_path=path.relative_to(arguments.project_root).as_posix(),
    )
    if pairwise is not None and pairwise.decision.value == "inconclusive":
        state_decision = "inconclusive"
    else:
        state_decision = repository.load(candidate.policy_id).validation_result.decision
    if state_decision not in {"accepted", "rejected", "inconclusive"}:
        raise RuntimeError(f"Unexpected Candidate decision: {state_decision}")
    state = record_candidate_decision(
        state,
        candidate,
        state_decision,
        settings.evolution,
        champion_id=repository.champion().policy_id,
        completed_at=bundle.created_at,
    )
    write_evolution_state(
        state,
        evolution_state_path(arguments.project_root, arguments.evolution_id),
    )
    print(
        json.dumps(
            {
                "gate_bundle": bundle.model_dump(mode="json"),
                "promoted_policy": promoted.model_dump(mode="json") if promoted else None,
            },
            indent=2,
        )
    )


def _status(arguments: argparse.Namespace) -> None:
    report_path = arguments.pattern_report
    if not report_path.is_absolute():
        report_path = arguments.project_root / report_path
    report = FailurePatternReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    settings = load_settings(
        arguments.project_root / "configs", arguments.project_root / ".env"
    )
    repository = PolicyRepository(arguments.project_root / "policies")
    champion = repository.champion()
    state = load_or_rebuild_evolution_state(
        arguments.project_root, arguments.evolution_id, settings.evolution
    )
    stop = proposal_stop_condition(
        state,
        settings.evolution,
        champion,
        has_repeated_failure_pattern=any(
            pattern.failed_runs >= 2 for pattern in report.patterns
        ),
    )
    print(
        json.dumps(
            {
                "state": state.model_dump(mode="json"),
                "proposal_stop": stop.model_dump(mode="json"),
                "remaining_mutations": remaining_single_field_mutations(
                    champion, state.progress.attempted_mutations
                ),
            },
            indent=2,
        )
    )


def _rollback(arguments: argparse.Namespace) -> None:
    repository = PolicyRepository(arguments.project_root / "policies")
    settings = load_settings(
        arguments.project_root / "configs", arguments.project_root / ".env"
    )
    state = load_or_rebuild_evolution_state(
        arguments.project_root, arguments.evolution_id, settings.evolution
    )
    if state.pending_candidate_id is not None or state.current_candidate_ids:
        raise RuntimeError("Cannot roll back while the current generation has Candidates")
    restored = rollback_last_known_good(
        repository,
        report_path=arguments.report_path,
        reason=arguments.reason,
    )
    state = record_champion_rollback(state, restored.policy_id)
    write_evolution_state(
        state,
        evolution_state_path(arguments.project_root, arguments.evolution_id),
    )
    print(restored.model_dump_json(indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded EvoDev Policy evolution stages.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    aggregate = commands.add_parser("aggregate", help="Aggregate Train-only failure evidence.")
    aggregate.add_argument("--experiment-ids", nargs="+", required=True)
    aggregate.add_argument("--report-id", required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.set_defaults(handler=_aggregate)

    collect = commands.add_parser("collect-train", help="Run paid Train evidence collection.")
    collect.add_argument("--experiment-id", required=True)
    collect.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=2)
    collect.add_argument("--confirm-paid", action="store_true")
    collect.set_defaults(handler=_collect_train)

    propose = commands.add_parser("propose", help="Make one paid Train-only proposal call.")
    propose.add_argument("--pattern-report", type=Path, required=True)
    propose.add_argument("--evolution-id", required=True)
    propose.add_argument("--confirm-paid", action="store_true")
    propose.set_defaults(handler=_propose)

    validate = commands.add_parser("validate", help="Run paid 3x3 pairwise Validation.")
    validate.add_argument("--candidate-id", required=True)
    validate.add_argument("--evolution-id", required=True)
    validate.add_argument("--confirm-paid", action="store_true")
    validate.set_defaults(handler=_validate)

    status = commands.add_parser(
        "status", help="Rebuild or inspect free Evolution budget state."
    )
    status.add_argument("--evolution-id", required=True)
    status.add_argument("--pattern-report", type=Path, required=True)
    status.set_defaults(handler=_status)

    rollback = commands.add_parser("rollback", help="Restore previous champion pointer.")
    rollback.add_argument("--evolution-id", required=True)
    rollback.add_argument("--report-path", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.set_defaults(handler=_rollback)
    return parser


def main() -> None:
    parser = _parser()
    arguments = parser.parse_args()
    arguments.project_root = arguments.project_root.resolve()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
