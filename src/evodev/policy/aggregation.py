"""Deterministic aggregation of learnable Train failure patterns."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from evodev.evaluation import FailureType
from evodev.experience import is_reflection_eligible
from evodev.policy.models import FailurePattern, TrainRunEvidence


def aggregate_failure_patterns(train_runs: list[TrainRunEvidence]) -> list[FailurePattern]:
    grouped: dict[FailureType, list[TrainRunEvidence]] = defaultdict(list)
    for run in train_runs:
        if is_reflection_eligible(run.failure_type):
            grouped[run.failure_type].append(run)
    return [
        FailurePattern(
            failure_type=failure_type,
            failed_runs=len(runs),
            edited_before_tests=sum(not run.inspected_tests_before_edit for run in runs),
            avg_patch_attempts=round(fmean(run.patch_attempts for run in runs), 4),
            run_ids=sorted(run.run_id for run in runs),
        )
        for failure_type, runs in sorted(grouped.items(), key=lambda item: str(item[0]))
    ]
