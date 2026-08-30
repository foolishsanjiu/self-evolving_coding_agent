"""Retrieval and trace-based experience utilization metrics."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from evodev.experience.models import RetrievalResult
from evodev.trajectory import TraceAnalyzer


class ExperienceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_attempts: int = Field(ge=0)
    retrieval_hits: int = Field(ge=0)
    retrieval_hit_rate: float = Field(ge=0, le=1)
    measurable_retrievals: int = Field(ge=0)
    utilized_retrievals: int = Field(ge=0)
    experience_utilization_rate: float = Field(ge=0, le=1)


def summarize_experience_metrics(
    retrievals: dict[str, RetrievalResult],
    trajectory_paths: dict[str, Path],
    baseline_trajectory_paths: dict[str, Path] | None = None,
) -> ExperienceMetrics:
    hits = sum(result.hit for result in retrievals.values())
    measurable = 0
    utilized = 0
    for run_id, result in retrievals.items():
        targets = {
            target for item in result.selected for target in item.behavior_targets
        }
        if not targets or run_id not in trajectory_paths:
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
        utilized += any(
            bool(features.get(target)) and not bool(baseline_features.get(target))
            for target in targets
        )
    attempts = len(retrievals)
    return ExperienceMetrics(
        retrieval_attempts=attempts,
        retrieval_hits=hits,
        retrieval_hit_rate=round(hits / attempts, 4) if attempts else 0,
        measurable_retrievals=measurable,
        utilized_retrievals=utilized,
        experience_utilization_rate=(
            round(utilized / measurable, 4) if measurable else 0
        ),
    )
