from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.benchmark import BenchmarkLoader
from evodev.config import load_settings
from evodev.evaluation import EvaluationGrades, EvaluationResult, ExperimentManifest
from evodev.evaluation.experience_experiment import (
    ExperienceExperimentRunner,
    assert_controlled_conditions,
    prepare_validation_baseline,
)
from evodev.experience import (
    ExperienceRetriever,
    ExperienceSource,
    ExperienceStatus,
    StoredExperience,
    build_retrieval_query,
    create_snapshot,
    load_snapshot,
    summarize_experience_metrics,
    write_snapshot,
)
from evodev.trajectory.models import utc_now


@pytest.fixture
def retrieval_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"retrieval_{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def _experience(
    experience_id: str = "exp_validation",
    status: ExperienceStatus = ExperienceStatus.ACTIVE,
    recommendation: str = "Inspect tests first and align exception message contracts.",
) -> StoredExperience:
    now = utc_now()
    return StoredExperience(
        experience_id=experience_id,
        task_types=["exception_handling"],
        trigger="Target test rejects a ValueError message for invalid input",
        recommendation=recommendation,
        rationale="Exception message assertions are part of the validation contract.",
        keywords=["exception_message_contract", "validation_errors"],
        confidence=0.88,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _source(experience_id: str = "exp_validation") -> ExperienceSource:
    return ExperienceSource(
        experience_id=experience_id,
        reflection_id="reflection_1",
        task_id="task_002",
        run_id="run_task_002_r01",
        trajectory_path="runs/exp-baseline-v1/run_task_002_r01",
        evaluation_report_path="evaluation_runs/exp-baseline-v1/instances/task_002/report.json",
    )


def _task(task_id: str):
    return next(
        task
        for task in BenchmarkLoader(Path("benchmarks")).load_tasks()
        if task.config.task_id == task_id
    )


def test_query_uses_public_task_metadata_and_repository_context() -> None:
    query = build_retrieval_query(_task("task_008"))

    assert query.task_type == "exception_handling"
    assert "config_reader.py" in query.repository_context
    assert query.keywords
    assert "hidden_tests" not in query.repository_context


def test_relevant_retrieval_is_bounded_and_excludes_same_task() -> None:
    retriever = ExperienceRetriever([_experience()], [_source()], top_k=3, max_chars=2_500)

    result = retriever.retrieve(build_retrieval_query(_task("task_008")))
    same_task = retriever.retrieve(build_retrieval_query(_task("task_002")))
    disabled = retriever.retrieve(build_retrieval_query(_task("task_008")), "disabled")

    assert result.hit is True
    assert len(result.selected) == 1
    assert result.selected[0].task_type_match == 1
    assert result.prompt_chars <= 2_500
    assert result.prompt_section.startswith("Relevant Past Experience:")
    assert same_task.selected == []
    assert disabled.prompt_section == ""


def test_random_ablation_is_deterministic_and_keeps_irrelevant_control() -> None:
    retriever = ExperienceRetriever([_experience()], [_source()], random_seed=7)
    query = build_retrieval_query(_task("task_007"))

    first = retriever.retrieve(query, "random")
    second = retriever.retrieve(query, "random")

    assert [item.experience.experience_id for item in first.selected] == [
        item.experience.experience_id for item in second.selected
    ]
    assert len(first.selected) == 1
    assert first.hit is False


def test_retrieval_uses_only_active_experience_and_respects_budget() -> None:
    long = _experience(recommendation="test first " + "x" * 4_000)
    candidate = _experience("exp_candidate", ExperienceStatus.CANDIDATE)
    retriever = ExperienceRetriever([long, candidate], [_source()], max_chars=2_000)

    result = retriever.retrieve(build_retrieval_query(_task("task_008")))

    assert len(result.selected) == 1
    assert result.selected[0].experience.experience_id == long.experience_id
    assert result.prompt_chars <= 2_000


def test_snapshot_is_active_only_and_hash_verified(retrieval_root: Path) -> None:
    snapshot = create_snapshot(
        "experience-v001",
        [_experience(), _experience("exp_candidate", ExperienceStatus.CANDIDATE)],
        [_source()],
    )
    path = retrieval_root / "experience-v001.json"
    write_snapshot(snapshot, path)

    loaded = load_snapshot(path)
    assert [item.experience_id for item in loaded.experiences] == ["exp_validation"]
    assert len(loaded.sources) == 1

    path.write_text(
        path.read_text(encoding="utf-8").replace('"confidence": 0.88', '"confidence": 0.5'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash"):
        load_snapshot(path)


def test_experience_metrics_use_retrieval_and_public_trace_features(
    retrieval_root: Path,
) -> None:
    retrieval = ExperienceRetriever([_experience()], [_source()]).retrieve(
        build_retrieval_query(_task("task_008"))
    )
    run_path = retrieval_root / "run_task_008_r01"
    baseline_path = retrieval_root / "baseline_task_008_r01"
    run_path.mkdir()
    baseline_path.mkdir()
    (run_path / "trace_features.json").write_text(
        '{"inspected_tests_before_edit": true}', encoding="utf-8"
    )
    (baseline_path / "trace_features.json").write_text(
        '{"inspected_tests_before_edit": false}', encoding="utf-8"
    )

    metrics = summarize_experience_metrics(
        {"run_task_008_r01": retrieval},
        {"run_task_008_r01": run_path},
        {"run_task_008_r01": baseline_path},
    )

    assert metrics.retrieval_hit_rate == 1
    assert metrics.experience_utilization_rate == 1

    (baseline_path / "trace_features.json").write_text(
        '{"inspected_tests_before_edit": true}', encoding="utf-8"
    )
    unchanged = summarize_experience_metrics(
        {"run_task_008_r01": retrieval},
        {"run_task_008_r01": run_path},
        {"run_task_008_r01": baseline_path},
    )
    assert unchanged.experience_utilization_rate == 0


def test_controlled_manifest_allows_only_experience_fields() -> None:
    baseline = ExperimentManifest.model_validate_json(
        Path("baselines/exp-baseline-validation-v1/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    treatment = baseline.model_copy(
        update={
            "experiment_id": "exp-experience-v1",
            "experiment_version": "exp-experience-v1",
            "experience_version": "experience-v001",
            "experience_hash": "e" * 64,
            "experience_mode": "relevant",
            "experience_top_k": 3,
            "experience_max_chars": 2_500,
        }
    )

    assert_controlled_conditions(baseline, treatment)

    changed_model = treatment.model_copy(update={"model": "other-model"})
    with pytest.raises(ValueError, match="model"):
        assert_controlled_conditions(baseline, changed_model)


def test_frozen_v001_retrieves_only_relevant_validation_task() -> None:
    snapshot = load_snapshot(Path("experiences/experience-v001.json"))
    retriever = ExperienceRetriever(snapshot.experiences, snapshot.sources)
    selected = {
        task.config.task_id: bool(
            retriever.retrieve(build_retrieval_query(task), "relevant").selected
        )
        for task in BenchmarkLoader(Path("benchmarks")).load_tasks()
        if task.split == "validation"
    }

    assert selected == {"task_007": False, "task_008": True, "task_009": False}


def test_validation_baseline_derivation_is_offline_and_reproducible(
    retrieval_root: Path,
) -> None:
    source_manifest = Path("baselines/exp-baseline-v1/manifest.json")
    target_manifest = retrieval_root / "baselines" / "exp-baseline-v1" / "manifest.json"
    target_manifest.parent.mkdir(parents=True)
    target_manifest.write_text(source_manifest.read_text(encoding="utf-8"), encoding="utf-8")
    for index, task_id in enumerate(("task_007", "task_008", "task_009"), start=1):
        run_id = f"run_{task_id}_r01"
        instance = retrieval_root / "evaluation_runs" / "exp-baseline-v1" / "instances" / task_id
        run_path = retrieval_root / "runs" / "exp-baseline-v1" / run_id
        instance.mkdir(parents=True)
        run_path.mkdir(parents=True)
        result = EvaluationResult(
            task_id=task_id,
            agent_run_id=run_id,
            benchmark_version="1.0",
            benchmark_hash="b" * 64,
            grades=EvaluationGrades(),
            failure_type="RESOLVED" if index != 2 else "TARGET_TEST_FAILED",
            resolved=index != 2,
            valid_evaluation=True,
            started_at="2026-01-01T00:00:00+00:00",
            duration_ms=1,
        )
        (instance / "report.json").write_text(
            result.model_dump_json(), encoding="utf-8"
        )
        (run_path / "run.json").write_text(
            '{"started_at":"2026-01-01T00:00:00+00:00",'
            '"finished_at":"2026-01-01T00:00:01+00:00"}',
            encoding="utf-8",
        )
        (run_path / "events.jsonl").write_text("", encoding="utf-8")
        (run_path / "trace_features.json").write_text(
            '{"searched_before_edit":false,"inspected_tests_before_edit":false,'
            '"unique_files_read":0,"patch_attempts":0,"test_runs":0}',
            encoding="utf-8",
        )

    manifest, summary = prepare_validation_baseline(retrieval_root)

    assert manifest.benchmark_splits == ["validation"]
    assert summary.total_attempts == 3
    assert summary.resolved_attempts == 2


def test_experiment_runner_builds_a_controlled_manifest_without_api_call(
    retrieval_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark_manifest = BenchmarkLoader(Path("benchmarks")).verify_manifest()

    class FakeLoader:
        def __init__(self, root: Path) -> None:
            self.root = root

        def verify_manifest(self):
            return benchmark_manifest

    monkeypatch.setattr(
        "evodev.evaluation.experience_experiment.BenchmarkLoader", FakeLoader
    )
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    baseline_path = Path("baselines/exp-baseline-validation-v1/manifest.json")
    baseline = ExperimentManifest.model_validate_json(
        baseline_path.read_text(encoding="utf-8")
    )
    runner = ExperienceExperimentRunner(
        retrieval_root,
        load_settings(Path("configs")),
        Path("experiences/experience-v001.json"),
        experiment_id="exp-experience-v1",
        mode="relevant",
        baseline_manifest_path=baseline_path,
    )

    manifest = runner._manifest(baseline.tool_catalog_hash, baseline.sandbox_digest)

    assert manifest.experience_mode == "relevant"
    assert manifest.benchmark_splits == ["validation"]
    assert_controlled_conditions(baseline, manifest)


def test_frozen_task11_comparison_matches_arm_artifacts() -> None:
    root = Path("experiments/task11-validation-v1")
    comparison = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
    manifests = {}
    for arm in ("baseline", "relevant", "random"):
        arm_path = root / arm
        manifests[arm] = ExperimentManifest.model_validate_json(
            (arm_path / "manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads((arm_path / "summary.json").read_text(encoding="utf-8"))
        with (arm_path / "summary.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert comparison["arms"][arm]["resolved"] == summary["resolved_attempts"]
        assert comparison["arms"][arm]["total_tokens"] == sum(
            int(row["tokens"]) for row in rows
        )
        assert comparison["arms"][arm]["total_model_turns"] == sum(
            int(row["react_steps"]) for row in rows
        )

    assert_controlled_conditions(manifests["baseline"], manifests["relevant"])
    assert_controlled_conditions(manifests["baseline"], manifests["random"])
    relevant_metrics = json.loads(
        (root / "relevant" / "experience_metrics.json").read_text(encoding="utf-8")
    )
    assert relevant_metrics["experience_utilization_rate"] == 0
    assert comparison["interpretation"]["resolution_uplift_demonstrated"] is False
