"""Write complete, machine-readable Task 14 result artifacts."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from evodev.evaluation.final_experiment import (
    FinalExperimentManifest,
    FinalExperimentSummary,
    FinalRunResult,
    FinalRunResultsArtifact,
    build_final_run_plan,
    summarize_final_results,
)
from evodev.evaluation.models import EvaluationResult


class FinalArtifactVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    verified_runs: int = Field(ge=0)
    verified_instances: int = Field(ge=0)
    summary_matches: bool
    csv_matches: bool
    valid: bool


def write_final_result_artifacts(
    results_root: Path,
    manifest: FinalExperimentManifest,
    results: list[FinalRunResult],
) -> FinalExperimentSummary:
    root = results_root.resolve()
    manifest_path = root / "experiment_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Frozen Final Manifest is missing")
    stored = FinalExperimentManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if stored != manifest:
        raise ValueError("Final results do not match the frozen Manifest")
    output_paths = [
        root / "run_results.json",
        root / "summary.json",
        root / "summary.csv",
    ]
    if any(path.exists() for path in output_paths):
        raise FileExistsError("Final result artifacts already exist")

    summary = summarize_final_results(manifest, results)
    artifact = FinalRunResultsArtifact(
        experiment_id=manifest.experiment_id,
        results=results,
    )
    (root / "run_results.json").write_text(
        artifact.model_dump_json(indent=2), encoding="utf-8"
    )
    (root / "summary.json").write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )
    _write_run_csv(root / "summary.csv", results)
    return summary


def _write_run_csv(path: Path, results: list[FinalRunResult]) -> None:
    path.write_text(_render_run_csv(results), encoding="utf-8", newline="")


def _render_run_csv(results: list[FinalRunResult]) -> str:
    fields = [
        "variant_id",
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
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for result in results:
        writer.writerow(result.model_dump(mode="json"))
    return stream.getvalue()


def verify_final_result_artifacts(results_root: Path) -> FinalArtifactVerification:
    """Recompute every public aggregate and link each run to its evaluator report."""
    root = results_root.resolve(strict=True)
    manifest = FinalExperimentManifest.model_validate_json(
        (root / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    artifact = FinalRunResultsArtifact.model_validate_json(
        (root / "run_results.json").read_text(encoding="utf-8")
    )
    stored_summary = FinalExperimentSummary.model_validate_json(
        (root / "summary.json").read_text(encoding="utf-8")
    )
    if artifact.experiment_id != manifest.experiment_id:
        raise ValueError("Run results do not match the Final Manifest experiment")
    if stored_summary.experiment_id != manifest.experiment_id:
        raise ValueError("Summary does not match the Final Manifest experiment")

    expected_ids = {item.agent_run_id for item in build_final_run_plan(manifest)}
    actual_ids = {item.agent_run_id for item in artifact.results}
    if actual_ids != expected_ids:
        raise ValueError("Final run IDs do not match the frozen run plan")

    recomputed = summarize_final_results(manifest, artifact.results)
    if recomputed.model_dump(exclude={"created_at"}) != stored_summary.model_dump(
        exclude={"created_at"}
    ):
        raise ValueError("Final summary does not match recomputed run results")

    csv_path = root / "summary.csv"
    if csv_path.read_text(encoding="utf-8") != _render_run_csv(artifact.results):
        raise ValueError("Final CSV does not match run_results.json")

    instances = 0
    for result in artifact.results:
        run_parts = result.agent_run_id.rsplit("-r", maxsplit=1)
        if len(run_parts) != 2 or not run_parts[1].isdigit():
            raise ValueError(f"Invalid Final run ID: {result.agent_run_id}")
        repetition = int(run_parts[1])
        report_path = (
            root
            / "instances"
            / result.variant_id.value
            / result.task_id
            / f"attempt_{repetition:02d}"
            / "report.json"
        )
        report = EvaluationResult.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        if (
            report.task_id != result.task_id
            or report.agent_run_id != result.agent_run_id
            or report.resolved != result.resolved
            or report.valid_evaluation != result.valid_evaluation
            or report.failure_type != result.failure_type
            or report.evaluator_version != manifest.evaluator_version
            or report.benchmark_version != manifest.benchmark_version
            or report.benchmark_hash != manifest.benchmark_hash
        ):
            raise ValueError(
                f"Evaluator report does not match Final run: {result.agent_run_id}"
            )
        instances += 1

    return FinalArtifactVerification(
        experiment_id=manifest.experiment_id,
        verified_runs=len(artifact.results),
        verified_instances=instances,
        summary_matches=True,
        csv_matches=True,
        valid=True,
    )
