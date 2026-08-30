"""Explicit bounded-search stop conditions."""

from evodev.config import EvolutionSettings
from evodev.evolution.models import EvolutionProgress, EvolutionStop


def evolution_stop_condition(
    progress: EvolutionProgress,
    settings: EvolutionSettings,
    *,
    has_repeated_failure_pattern: bool,
    all_single_field_mutations_attempted: bool,
) -> EvolutionStop:
    if progress.api_budget_exhausted:
        return EvolutionStop(should_stop=True, reason="API or evaluation budget exhausted")
    if progress.generation > settings.max_generations:
        return EvolutionStop(should_stop=True, reason="Maximum generations reached")
    if progress.generations_without_improvement >= settings.no_improvement_patience:
        return EvolutionStop(should_stop=True, reason="No-improvement patience reached")
    if not has_repeated_failure_pattern:
        return EvolutionStop(should_stop=True, reason="No repeated Train failure pattern")
    if all_single_field_mutations_attempted:
        return EvolutionStop(should_stop=True, reason="All single-field mutations attempted")
    if progress.candidates_in_generation >= settings.max_candidates_per_generation:
        return EvolutionStop(should_stop=True, reason="Candidate budget for generation reached")
    return EvolutionStop(should_stop=False)
