import json
from pathlib import Path

import pytest

from evodev.config import load_settings
from evodev.evaluation.experience_experiment import (
    audit_validation_retrieval,
    build_experience_arm_preflight,
    require_experience_paid_confirmation,
)


def test_v2_validation_retrieval_audit_is_public_and_reproducible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accessed: list[Path] = []
    original_read_text = Path.read_text

    def tracked_read_text(path: Path, *args, **kwargs) -> str:
        accessed.append(path.resolve())
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)
    audit = audit_validation_retrieval(
        Path("."),
        Path("experiences/experience-v002.json"),
        Path("benchmarks-v2"),
    )
    frozen = json.loads(
        Path(
            "experiments/benchmark-v2-experience-validation-plan-v1/"
            "retrieval-audit.json"
        ).read_text(encoding="utf-8")
    )

    assert audit == frozen
    assert audit["public_metadata_only"] is True
    assert audit["task_count"] == 5
    assert audit["hit_tasks"] == 1
    assert audit["hit_rate"] == 0.2
    assert [task["task_id"] for task in audit["tasks"] if task["hit"]] == [
        "task_113"
    ]
    benchmark_root = Path("benchmarks-v2").resolve()
    benchmark_reads = [
        path.relative_to(benchmark_root)
        for path in accessed
        if path.is_relative_to(benchmark_root)
    ]
    assert all(path.parts[0] != "test" for path in benchmark_reads)
    assert all("hidden_tests" not in path.parts for path in benchmark_reads)
    assert all(path.name != "gold.patch" for path in benchmark_reads)


def test_v2_relevant_arm_preflight_is_offline_and_exact() -> None:
    plan = build_experience_arm_preflight(
        Path("."),
        load_settings(Path("configs")),
        Path("experiences/experience-v002.json"),
        experiment_id="exp-experience-v2-validation-v1",
        mode="relevant",
        repetitions=2,
        benchmark_root=Path("benchmarks-v2"),
        baseline_manifest_path=Path(
            "evaluation_runs/__preflight_missing__/manifest.json"
        ),
    )

    assert plan["task_ids"] == [
        "task_109",
        "task_110",
        "task_111",
        "task_112",
        "task_113",
    ]
    assert plan["expected_paid_calls"] == 10
    assert len(plan["runs"]) == 10
    assert len({run["agent_run_id"] for run in plan["runs"]}) == 10
    assert plan["baseline_manifest_ready"] is False
    assert plan["requires_paid_confirmation"] is True


def test_v2_train_holdout_preflight_selects_only_the_frozen_hit_task() -> None:
    plan = build_experience_arm_preflight(
        Path("."),
        load_settings(Path("configs")),
        Path("experiences/experience-v003.json"),
        experiment_id="exp-experience-v003-train-holdout-v1",
        mode="relevant",
        repetitions=2,
        benchmark_root=Path("benchmarks-v2"),
        baseline_manifest_path=Path(
            "evaluation_runs/__train_holdout_preflight_missing__/manifest.json"
        ),
        split="train",
        task_ids=["task_101"],
    )

    assert plan["benchmark_splits"] == ["train"]
    assert plan["task_ids"] == ["task_101"]
    assert plan["expected_paid_calls"] == 2
    assert [run["agent_run_id"] for run in plan["runs"]] == [
        "run_task_101_r01",
        "run_task_101_r02",
    ]
    assert plan["experience_version"] == "experience-v003"
    assert plan["experience_consumer"] == "legacy-v1"
    assert plan["baseline_manifest_ready"] is False


def test_v2_train_holdout_preflight_rejects_non_train_task() -> None:
    with pytest.raises(ValueError, match="not in the train split"):
        build_experience_arm_preflight(
            Path("."),
            load_settings(Path("configs")),
            Path("experiences/experience-v004.json"),
            experiment_id="exp-experience-v004-train-holdout-v1",
            mode="relevant",
            repetitions=2,
            benchmark_root=Path("benchmarks-v2"),
            baseline_manifest_path=Path(
                "evaluation_runs/__train_holdout_preflight_missing__/manifest.json"
            ),
            split="train",
            task_ids=["task_109"],
        )


def test_experience_validation_requires_explicit_paid_confirmation() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        require_experience_paid_confirmation(False)

    require_experience_paid_confirmation(True)
