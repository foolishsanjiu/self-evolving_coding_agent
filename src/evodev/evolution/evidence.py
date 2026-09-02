"""Build mutation evidence strictly from persisted Train evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from evodev.benchmark import BenchmarkLoader
from evodev.evaluation.models import EvaluationResult
from evodev.experience import is_reflection_eligible
from evodev.policy.aggregation import aggregate_failure_patterns
from evodev.policy.models import TrainRunEvidence
from evodev.trajectory import TraceAnalyzer

from .models import FailureEvidenceExclusion, FailurePatternReport


def aggregate_train_failure_report(
    project_root: Path,
    experiment_ids: list[str],
    *,
    report_id: str,
    benchmark_root: Path = Path("benchmarks"),
) -> FailurePatternReport:
    """Load public run evidence while rejecting non-Train provenance."""
    root = project_root.resolve()
    resolved_benchmark_root = (
        benchmark_root if benchmark_root.is_absolute() else root / benchmark_root
    )
    tasks = {
        task.config.task_id: task
        for task in BenchmarkLoader(resolved_benchmark_root).load_tasks()
    }
    evidence = []
    excluded_failures = []
    for experiment_id in experiment_ids:
        experiment_path = root / "evaluation_runs" / experiment_id
        if not experiment_path.is_dir():
            raise FileNotFoundError(f"Evaluation experiment not found: {experiment_id}")
        for report_path in sorted((experiment_path / "instances").rglob("report.json")):
            result = EvaluationResult.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            task = tasks.get(result.task_id)
            if task is None:
                raise ValueError(f"Unknown benchmark task in evaluation: {result.task_id}")
            if task.split != "train":
                continue
            if result.resolved:
                continue
            run_id = f"{experiment_id}/{result.agent_run_id}"
            if not is_reflection_eligible(result.failure_type):
                excluded_failures.append(
                    FailureEvidenceExclusion(
                        run_id=run_id,
                        failure_type=result.failure_type,
                        reason="failure_not_reflection_eligible",
                    )
                )
                continue
            run_path = root / "runs" / experiment_id / result.agent_run_id
            features_path = run_path / "trace_features.json"
            if features_path.is_file():
                features = json.loads(features_path.read_text(encoding="utf-8"))
            else:
                events = TraceAnalyzer.load_events(run_path / "events.jsonl")
                features = TraceAnalyzer.analyze(events)
            evidence.append(
                TrainRunEvidence(
                    run_id=run_id,
                    failure_type=result.failure_type,
                    inspected_tests_before_edit=bool(
                        features["inspected_tests_before_edit"]
                    ),
                    patch_attempts=int(features["patch_attempts"]),
                )
            )
    if not evidence and not excluded_failures:
        raise ValueError("No failed Train evaluations were found in the selected experiments")
    return FailurePatternReport(
        report_id=report_id,
        source_experiment_ids=experiment_ids,
        patterns=aggregate_failure_patterns(evidence),
        total_failed_runs=len(evidence) + len(excluded_failures),
        eligible_failed_runs=len(evidence),
        excluded_failures=excluded_failures,
    )


def write_failure_pattern_report(report: FailurePatternReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
