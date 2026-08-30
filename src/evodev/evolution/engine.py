"""Small orchestration helpers that never overwrite an existing Policy."""

from __future__ import annotations

from pathlib import Path

from evodev.evolution.models import CandidateGateBundle, GateDecision
from evodev.policy.models import PolicyValidationResult, VersionedPolicy
from evodev.policy.versioning import PolicyRepository


def write_gate_bundle(bundle: CandidateGateBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")


def finalize_candidate(
    repository: PolicyRepository,
    bundle: CandidateGateBundle,
    *,
    report_path: str,
) -> VersionedPolicy | None:
    """Persist a conclusive gate decision; inconclusive runs remain pending."""
    if not bundle.schema_gate.passed:
        decision = "rejected"
        reason = bundle.schema_gate.reason
    elif bundle.smoke_gate is None or not bundle.smoke_gate.passed:
        decision = "rejected"
        reason = (
            bundle.smoke_gate.reason
            if bundle.smoke_gate
            else "Smoke gate was not executed."
        )
    elif bundle.pairwise_gate is None:
        raise ValueError("Pairwise gate is required after Schema and Smoke pass")
    elif bundle.pairwise_gate.decision == GateDecision.INCONCLUSIVE:
        return None
    else:
        decision = bundle.pairwise_gate.decision.value
        reason = bundle.pairwise_gate.reason

    return repository.decide_candidate(
        bundle.candidate_id,
        PolicyValidationResult(
            decision=decision,
            report_path=report_path,
            reason=reason,
        ),
    )


def rollback_last_known_good(
    repository: PolicyRepository,
    *,
    report_path: str,
    reason: str,
) -> VersionedPolicy:
    return repository.rollback_champion(
        PolicyValidationResult(
            decision="rolled_back",
            report_path=report_path,
            reason=reason,
        )
    )
