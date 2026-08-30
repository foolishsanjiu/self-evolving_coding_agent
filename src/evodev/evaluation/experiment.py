"""Controlled experiment manifests and automatic metric aggregation."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import fmean

from evodev.evaluation.models import (
    EvaluationResult,
    ExperimentManifest,
    ExperimentSummary,
    TrajectoryMetrics,
)
from evodev.trajectory import TraceAnalyzer


def _mean(values: list[int | bool]) -> float:
    return round(fmean(values), 4) if values else 0.0


class TrajectoryMetricReader:
    """Derive efficiency and behavior metrics only from persisted public events."""

    @staticmethod
    def read(run_path: Path) -> TrajectoryMetrics:
        metadata = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
        events = TraceAnalyzer.load_events(run_path / "events.jsonl")
        features_path = run_path / "trace_features.json"
        features = (
            json.loads(features_path.read_text(encoding="utf-8"))
            if features_path.is_file()
            else TraceAnalyzer.analyze(events)
        )
        started = datetime.fromisoformat(metadata["started_at"])
        finished = datetime.fromisoformat(metadata["finished_at"])
        model_turns = [event for event in events if event.get("type") == "MODEL_TURN"]
        tokens = sum(
            int(event.get("data", {}).get("input_tokens", 0))
            + int(event.get("data", {}).get("output_tokens", 0))
            for event in model_turns
        )
        return TrajectoryMetrics(
            react_steps=len(model_turns),
            tool_calls=sum(event.get("type") == "TOOL_CALL" for event in events),
            tokens=tokens,
            latency_ms=max(0, round((finished - started).total_seconds() * 1000)),
            searched_before_edit=bool(features["searched_before_edit"]),
            inspected_tests_before_edit=bool(features["inspected_tests_before_edit"]),
            patch_attempts=int(features["patch_attempts"]),
        )


class ExperimentReporter:
    """Persist fixed conditions plus primary, efficiency, and behavioral metrics."""

    def __init__(self, experiment_path: Path, manifest: ExperimentManifest) -> None:
        self.path = experiment_path.resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest = manifest
        manifest_path = self.path / "manifest.json"
        if manifest_path.exists():
            stored = ExperimentManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if stored != manifest:
                raise ValueError("Experiment manifest is already frozen with other conditions")
        else:
            manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def summarize(
        self,
        results: list[EvaluationResult],
        trajectory_paths: dict[str, Path],
    ) -> ExperimentSummary:
        metrics = {
            result.agent_run_id: TrajectoryMetricReader.read(
                trajectory_paths[result.agent_run_id]
            )
            for result in results
            if result.agent_run_id in trajectory_paths
        }
        valid = [result for result in results if result.valid_evaluation]
        resolved = sum(result.resolved for result in valid)
        metric_values = list(metrics.values())
        summary = ExperimentSummary(
            experiment_id=self.manifest.experiment_id,
            total_attempts=len(results),
            valid_evaluated_attempts=len(valid),
            resolved_attempts=resolved,
            resolution_rate=round(resolved / len(valid), 4) if valid else 0,
            average_react_steps=_mean([item.react_steps for item in metric_values]),
            average_tool_calls=_mean([item.tool_calls for item in metric_values]),
            average_tokens=_mean([item.tokens for item in metric_values]),
            average_latency_ms=_mean([item.latency_ms for item in metric_values]),
            search_before_edit_rate=_mean(
                [item.searched_before_edit for item in metric_values]
            ),
            test_inspection_before_edit_rate=_mean(
                [item.inspected_tests_before_edit for item in metric_values]
            ),
            average_patch_attempts=_mean([item.patch_attempts for item in metric_values]),
            failure_distribution=dict(Counter(result.failure_type for result in results)),
        )
        (self.path / "summary.json").write_text(
            summary.model_dump_json(indent=2), encoding="utf-8"
        )
        self._write_csv(results, metrics)
        return summary

    def _write_csv(
        self,
        results: list[EvaluationResult],
        metrics: dict[str, TrajectoryMetrics],
    ) -> None:
        fields = [
            "task_id",
            "agent_run_id",
            "resolved",
            "valid_evaluation",
            "failure_type",
            "react_steps",
            "tool_calls",
            "tokens",
            "latency_ms",
            "searched_before_edit",
            "inspected_tests_before_edit",
            "patch_attempts",
        ]
        with (self.path / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for result in results:
                metric = metrics.get(result.agent_run_id)
                writer.writerow(
                    {
                        "task_id": result.task_id,
                        "agent_run_id": result.agent_run_id,
                        "resolved": result.resolved,
                        "valid_evaluation": result.valid_evaluation,
                        "failure_type": result.failure_type.value,
                        "react_steps": metric.react_steps if metric else "",
                        "tool_calls": metric.tool_calls if metric else "",
                        "tokens": metric.tokens if metric else "",
                        "latency_ms": metric.latency_ms if metric else "",
                        "searched_before_edit": metric.searched_before_edit if metric else "",
                        "inspected_tests_before_edit": (
                            metric.inspected_tests_before_edit if metric else ""
                        ),
                        "patch_attempts": metric.patch_attempts if metric else "",
                    }
                )
