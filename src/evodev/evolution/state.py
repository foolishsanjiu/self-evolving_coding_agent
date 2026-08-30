"""File-backed Generation, Candidate, and Patience state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from evodev.config import EvolutionSettings
from evodev.evolution.budget import evolution_stop_condition
from evodev.evolution.models import (
    CandidateGateBundle,
    EvolutionGenerationRecord,
    EvolutionProgress,
    EvolutionState,
    EvolutionStop,
)
from evodev.policy.models import VersionedPolicy
from evodev.policy.versioning import PolicyRepository
from evodev.trajectory.models import utc_now


def evolution_state_path(project_root: Path, evolution_id: str) -> Path:
    return project_root / "evolution" / evolution_id / "progress.json"


def write_evolution_state(state: EvolutionState, path: Path) -> None:
    """Atomically persist deterministic JSON suitable for Git audit."""
    payload = state.model_dump(mode="json")
    payload["progress"]["attempted_mutations"] = sorted(
        payload["progress"]["attempted_mutations"]
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_evolution_state(path: Path) -> EvolutionState:
    if not path.is_file():
        raise FileNotFoundError(f"Evolution state does not exist: {path}")
    return EvolutionState.model_validate_json(path.read_text(encoding="utf-8"))


def _transition(candidate: VersionedPolicy) -> tuple[str, str, str]:
    if candidate.mutation is None:
        raise ValueError("Candidate has no Mutation")
    return (
        candidate.mutation.field,
        str(candidate.mutation.old_value),
        str(candidate.mutation.new_value),
    )


def register_candidate(
    state: EvolutionState,
    candidate: VersionedPolicy,
    settings: EvolutionSettings,
) -> EvolutionState:
    """Bind one pending Candidate to the current generation."""
    if state.pending_candidate_id is not None:
        raise ValueError("Current generation already has a Candidate awaiting validation")
    if candidate.parent_id != state.champion_id:
        raise ValueError("Candidate parent does not match the generation Champion")
    if candidate.policy_id in state.current_candidate_ids:
        raise ValueError("Candidate is already registered in the current generation")
    if len(state.current_candidate_ids) >= settings.max_candidates_per_generation:
        raise ValueError("Candidate budget for generation reached")

    updated = state.model_copy(deep=True)
    updated.current_candidate_ids.append(candidate.policy_id)
    updated.pending_candidate_id = candidate.policy_id
    updated.progress.candidates_in_generation = len(updated.current_candidate_ids)
    updated.progress.attempted_mutations.add(_transition(candidate))
    updated.updated_at = utc_now()
    return EvolutionState.model_validate(updated.model_dump())


def record_candidate_decision(
    state: EvolutionState,
    candidate: VersionedPolicy,
    decision: Literal["accepted", "rejected", "inconclusive"],
    settings: EvolutionSettings,
    *,
    champion_id: str,
    completed_at: str,
) -> EvolutionState:
    """Record a Gate decision and roll over a completed generation."""
    if state.pending_candidate_id != candidate.policy_id:
        raise ValueError("Gate decision does not match the pending Candidate")
    if decision == "accepted" and champion_id == state.champion_id:
        raise ValueError("Accepted Candidate must produce a new Champion")
    if decision != "accepted" and champion_id != state.champion_id:
        raise ValueError("Rejected or inconclusive Candidate cannot change Champion")

    updated = state.model_copy(deep=True)
    if decision == "inconclusive":
        updated.updated_at = utc_now()
        return EvolutionState.model_validate(updated.model_dump())

    updated.pending_candidate_id = None
    generation_complete = (
        decision == "accepted"
        or len(updated.current_candidate_ids) >= settings.max_candidates_per_generation
    )
    if not generation_complete:
        updated.updated_at = utc_now()
        return EvolutionState.model_validate(updated.model_dump())

    improved = decision == "accepted"
    updated.completed_generations.append(
        EvolutionGenerationRecord(
            generation=updated.progress.generation,
            champion_id=updated.champion_id,
            candidate_ids=list(updated.current_candidate_ids),
            outcome="improved" if improved else "no_improvement",
            accepted_candidate_id=candidate.policy_id if improved else None,
            completed_at=completed_at,
        )
    )
    updated.champion_id = champion_id
    updated.progress.generation += 1
    updated.progress.candidates_in_generation = 0
    updated.progress.generations_without_improvement = (
        0 if improved else updated.progress.generations_without_improvement + 1
    )
    updated.current_candidate_ids = []
    updated.updated_at = utc_now()
    return EvolutionState.model_validate(updated.model_dump())


def _promoted_policy_id(
    repository: PolicyRepository, candidate: VersionedPolicy
) -> str:
    matches = []
    for path in repository.root.glob("policy-v*.yaml"):
        policy = repository.load(path.stem)
        if policy.mutation_id == candidate.mutation_id:
            matches.append(policy.policy_id)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one promoted Policy for {candidate.policy_id}, found {len(matches)}"
        )
    return matches[0]


def rebuild_evolution_state(
    project_root: Path,
    evolution_id: str,
    settings: EvolutionSettings,
) -> EvolutionState:
    """Rebuild state from immutable Candidate snapshots and frozen final Gates."""
    repository = PolicyRepository(project_root / "policies")
    evolution_root = project_root / "evolution" / evolution_id
    candidate_dirs = sorted(evolution_root.glob("candidate-[0-9][0-9][0-9]"))
    if candidate_dirs:
        first_candidate = repository.load(candidate_dirs[0].name)
        if first_candidate.parent_id is None:
            raise ValueError("First Candidate has no parent Champion")
        initial_champion_id = first_candidate.parent_id
    else:
        initial_champion_id = repository.champion().policy_id

    state = EvolutionState(
        evolution_id=evolution_id,
        champion_id=initial_champion_id,
        progress=EvolutionProgress(),
    )
    for candidate_dir in candidate_dirs:
        candidate = repository.load(candidate_dir.name)
        state = register_candidate(state, candidate, settings)
        final_gate_path = candidate_dir / "gates-final.json"
        if not final_gate_path.is_file():
            continue
        gates = CandidateGateBundle.model_validate_json(
            final_gate_path.read_text(encoding="utf-8")
        )
        decision = candidate.validation_result.decision
        if decision not in {"accepted", "rejected"}:
            raise ValueError(f"Final Gate has non-final decision: {candidate.policy_id}")
        champion_id = (
            _promoted_policy_id(repository, candidate)
            if decision == "accepted"
            else state.champion_id
        )
        state = record_candidate_decision(
            state,
            candidate,
            decision,
            settings,
            champion_id=champion_id,
            completed_at=gates.created_at,
        )

    state.progress.attempted_mutations = repository.attempted_mutations()
    if state.champion_id != repository.champion().policy_id:
        raise ValueError("Rebuilt Evolution state does not match the Policy Champion")
    return EvolutionState.model_validate(state.model_dump())


def load_or_rebuild_evolution_state(
    project_root: Path,
    evolution_id: str,
    settings: EvolutionSettings,
) -> EvolutionState:
    path = evolution_state_path(project_root, evolution_id)
    if path.is_file():
        state = load_evolution_state(path)
        repository = PolicyRepository(project_root / "policies")
        if state.champion_id != repository.champion().policy_id:
            raise ValueError("Evolution state Champion does not match Policy repository")
        if state.progress.attempted_mutations != repository.attempted_mutations():
            raise ValueError("Evolution state Mutation history does not match Policy repository")
        return state
    state = rebuild_evolution_state(project_root, evolution_id, settings)
    write_evolution_state(state, path)
    return state


def remaining_single_field_mutations(
    champion: VersionedPolicy,
    attempted: set[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    search_space: dict[str, tuple[object, ...]] = {
        "inspect_tests_before_edit": ("off", "prefer", "require"),
        "prefer_search_before_read": (False, True),
        "max_react_steps": (10, 15, 20),
    }
    current = champion.policy.model_dump(mode="json")
    possible = {
        (field, str(current[field]), str(value))
        for field, values in search_space.items()
        for value in values
        if value != current[field]
    }
    return sorted(possible - attempted)


def record_champion_rollback(
    state: EvolutionState,
    restored_champion_id: str,
) -> EvolutionState:
    """Keep the current generation aligned with an explicit pointer rollback."""
    if state.pending_candidate_id is not None or state.current_candidate_ids:
        raise ValueError("Cannot roll back while the current generation has Candidates")
    updated = state.model_copy(deep=True)
    updated.champion_id = restored_champion_id
    updated.updated_at = utc_now()
    return EvolutionState.model_validate(updated.model_dump())


def proposal_stop_condition(
    state: EvolutionState,
    settings: EvolutionSettings,
    champion: VersionedPolicy,
    *,
    has_repeated_failure_pattern: bool,
) -> EvolutionStop:
    if state.pending_candidate_id is not None:
        return EvolutionStop(
            should_stop=True,
            reason=f"Candidate awaiting validation: {state.pending_candidate_id}",
        )
    remaining = remaining_single_field_mutations(
        champion, state.progress.attempted_mutations
    )
    return evolution_stop_condition(
        state.progress,
        settings,
        has_repeated_failure_pattern=has_repeated_failure_pattern,
        all_single_field_mutations_attempted=not remaining,
    )
