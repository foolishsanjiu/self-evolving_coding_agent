"""Write complete, machine-readable Task 14 result artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

from evodev.evaluation.final_experiment import (
    FinalExperimentManifest,
    FinalExperimentSummary,
    FinalRunResult,
    FinalRunResultsArtifact,
    summarize_final_results,
)


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
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(result.model_dump(mode="json"))
