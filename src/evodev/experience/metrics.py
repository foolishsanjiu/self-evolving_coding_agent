"""Retrieval and trace-based experience utilization metrics."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from evodev.experience.models import BehaviorTarget, RetrievalResult
from evodev.trajectory import TraceAnalyzer


class ExperienceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_attempts: int = Field(ge=0)
    retrieval_hits: int = Field(ge=0)
    retrieval_hit_rate: float = Field(ge=0, le=1)
    measurable_retrievals: int = Field(ge=0)
    adherent_retrievals: int = Field(ge=0)
    experience_adherence_rate: float = Field(ge=0, le=1)
    utilized_retrievals: int = Field(ge=0)
    experience_utilization_rate: float = Field(ge=0, le=1)


def _target_met(target: BehaviorTarget, features: dict[str, bool | int]) -> bool:
    observed = features.get(target.feature)
    if observed is None:
        return False
    if target.operator == "eq":
        return observed == target.value
    if isinstance(observed, bool) or isinstance(target.value, bool):
        return False
    if target.operator == "gte":
        return observed >= target.value
    return observed <= target.value


def _contract_met(targets: list[BehaviorTarget], features: dict[str, bool | int]) -> bool:
    return bool(targets) and all(_target_met(target, features) for target in targets)


def summarize_experience_metrics(
    retrievals: dict[str, RetrievalResult],
    trajectory_paths: dict[str, Path],
    baseline_trajectory_paths: dict[str, Path] | None = None,
) -> ExperienceMetrics:
    hits = sum(result.hit for result in retrievals.values())
    measurable = 0
    adherent = 0
    utilized = 0
    for run_id, result in retrievals.items():
        contracts: list[list[BehaviorTarget]] = []
        for item in result.selected:
            if item.execution_targets:
                contracts.append(item.execution_targets)
            elif item.behavior_targets:
                contracts.append(
                    [
                        BehaviorTarget(feature=target, operator="eq", value=True)
                        for target in item.behavior_targets
                    ]
                )
        if not contracts or run_id not in trajectory_paths:
            continue
        measurable += 1
        features_path = trajectory_paths[run_id] / "trace_features.json"
        features = (
            json.loads(features_path.read_text(encoding="utf-8"))
            if features_path.is_file()
            else TraceAnalyzer.analyze_file(trajectory_paths[run_id] / "events.jsonl")
        )
        baseline_features: dict[str, bool | int] = {}
        if baseline_trajectory_paths and run_id in baseline_trajectory_paths:
            baseline_path = baseline_trajectory_paths[run_id]
            baseline_features_path = baseline_path / "trace_features.json"
            baseline_features = (
                json.loads(baseline_features_path.read_text(encoding="utf-8"))
                if baseline_features_path.is_file()
                else TraceAnalyzer.analyze_file(baseline_path / "events.jsonl")
            )
        treatment_adherent = any(_contract_met(targets, features) for targets in contracts)
        baseline_adherent = any(_contract_met(targets, baseline_features) for targets in contracts)
        adherent += treatment_adherent
        utilized += treatment_adherent and not baseline_adherent
    attempts = len(retrievals)
    return ExperienceMetrics(
        retrieval_attempts=attempts,
        retrieval_hits=hits,
        retrieval_hit_rate=round(hits / attempts, 4) if attempts else 0,
        measurable_retrievals=measurable,
        adherent_retrievals=adherent,
        experience_adherence_rate=(round(adherent / measurable, 4) if measurable else 0),
        utilized_retrievals=utilized,
        experience_utilization_rate=(round(utilized / measurable, 4) if measurable else 0),
    )
