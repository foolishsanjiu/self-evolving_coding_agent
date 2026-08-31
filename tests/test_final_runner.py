from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.config import load_settings
from evodev.evaluation import final_experiment
from evodev.evaluation.demo import render_cli_demo
from evodev.evaluation.final_artifacts import write_final_result_artifacts
from evodev.evaluation.final_experiment import (
    FinalExperimentPlanner,
    FinalRunResult,
    FinalRuntimeIdentity,
    FinalVariantId,
    build_final_run_plan,
    load_final_experiment_config,
)
from evodev.evaluation.final_runner import (
    FinalExperimentRunner,
    require_final_paid_confirmation,
)
from evodev.evaluation.models import EvaluationGrades, EvaluationResult

CONFIG_PATH = Path("configs/experiments/final-v1.yaml")


def _preflight():
    config = load_final_experiment_config(CONFIG_PATH)
    settings = load_settings(Path("configs"))
    preflight = FinalExperimentPlanner(Path("."), settings, config).preflight(
        FinalRuntimeIdentity(
            git_commit="a" * 40,
            git_clean=True,
            sandbox_digest="sha256:final-image",
            tool_catalog_hash="b" * 64,
        )
    )
    ready = preflight.model_copy(
        update={
            "ready_to_freeze": True,
            "blocking_reasons": [],
            "accepted_case_studies": 2,
        }
    )
    return config, settings, ready


def _results() -> list[FinalRunResult]:
    results = []
    for variant in FinalVariantId:
        for task_id in ("task_010", "task_011", "task_012"):
            for repetition in range(1, 4):
                resolved = repetition == 1
                results.append(
                    FinalRunResult(
                        variant_id=variant,
                        task_id=task_id,
                        agent_run_id=(
                            f"final-v1-{variant.value}-{task_id}-r{repetition:02d}"
                        ),
                        resolved=resolved,
                        valid_evaluation=True,
                        failure_type=(
                            "RESOLVED" if resolved else "TARGET_TEST_FAILED"
                        ),
                        react_steps=5,
                        tool_calls=6,
                        tokens=100,
                        latency_ms=1_000,
                        searched_before_edit=True,
                        inspected_tests_before_edit=True,
                        patch_attempts=1,
                    )
                )
    return results


def test_final_run_plan_is_fixed_balanced_and_unique() -> None:
    _, _, preflight = _preflight()
    plan = build_final_run_plan(preflight.manifest)

    assert len(plan) == 36
    assert len({item.agent_run_id for item in plan}) == 36
    assert [item.variant_id for item in plan[:9]] == [FinalVariantId.BASELINE] * 9
    assert {
        (item.variant_id, item.task_id): sum(
            other.variant_id == item.variant_id and other.task_id == item.task_id
            for other in plan
        )
        for item in plan
    } == {
        (variant, task_id): 3
        for variant in FinalVariantId
        for task_id in ("task_010", "task_011", "task_012")
    }


def test_final_runner_requires_paid_confirmation_and_matching_freeze() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        require_final_paid_confirmation(False)
    require_final_paid_confirmation(True)

    config, settings, preflight = _preflight()
    runner = FinalExperimentRunner(
        Path("."), settings, config, preflight.manifest, preflight
    )
    assert len(runner.plan) == 36

    changed = preflight.manifest.model_copy(update={"model": "changed-model"})
    with pytest.raises(ValueError, match="do not match"):
        FinalExperimentRunner(Path("."), settings, config, changed, preflight)


def test_final_cli_checks_paid_confirmation_before_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["evodev-final", "run"])
    monkeypatch.setattr(
        final_experiment,
        "collect_final_runtime_identity",
        lambda *_: pytest.fail("Preflight must not run before paid confirmation"),
    )

    with pytest.raises(PermissionError, match="--confirm-paid"):
        final_experiment.main()


def test_final_runner_rejects_selective_resume() -> None:
    config, settings, preflight = _preflight()
    runner = FinalExperimentRunner(
        Path("."), settings, config, preflight.manifest, preflight
    )
    root = Path(".test_runtime") / f"final_resume_{uuid4().hex}"
    runner.results_root = root / "results"
    runner.runs_root = root / "runs"
    (runner.runs_root / "partial-run").mkdir(parents=True)
    try:
        with pytest.raises(FileExistsError, match="new Experiment Version"):
            runner._assert_fresh_execution()
    finally:
        shutil.rmtree(root)


def test_final_artifact_writer_requires_complete_results() -> None:
    _, _, preflight = _preflight()
    root = Path(".test_runtime") / f"final_artifacts_{uuid4().hex}"
    root.mkdir(parents=True)
    try:
        (root / "experiment_manifest.json").write_text(
            preflight.manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        summary = write_final_result_artifacts(
            root, preflight.manifest, _results()
        )

        assert len(summary.variants) == 4
        assert (root / "run_results.json").is_file()
        assert (root / "summary.json").is_file()
        with (root / "summary.csv").open(encoding="utf-8", newline="") as stream:
            assert len(list(csv.DictReader(stream))) == 36
        with pytest.raises(FileExistsError, match="already exist"):
            write_final_result_artifacts(root, preflight.manifest, _results())
    finally:
        shutil.rmtree(root)


def test_cli_demo_renders_only_persisted_public_artifacts() -> None:
    root = Path(".test_runtime") / f"final_demo_{uuid4().hex}"
    run_path = root / "run"
    report_path = root / "report.json"
    run_path.mkdir(parents=True)
    events = [
        {
            "type": "TOOL_CALL",
            "data": {
                "tool_call": {
                    "name": "search_code",
                    "arguments": {"query": "parser"},
                }
            },
        },
        {
            "type": "TOOL_CALL",
            "data": {
                "tool_call": {
                    "name": "read_file",
                    "arguments": {"path": "src/parser.py"},
                }
            },
        },
        {
            "type": "TOOL_CALL",
            "data": {"tool_call": {"name": "apply_patch", "arguments": {}}},
        },
        {
            "type": "TOOL_CALL",
            "data": {
                "tool_call": {
                    "name": "run_tests",
                    "arguments": {"test_path": "tests/test_parser.py"},
                }
            },
        },
    ]
    try:
        (run_path / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events), encoding="utf-8"
        )
        (run_path / "final.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")
        report_path.write_text(
            EvaluationResult(
                task_id="task_010",
                agent_run_id="final-v1-A-task_010-r01",
                benchmark_version="1.0",
                benchmark_hash="b" * 64,
                grades=EvaluationGrades(),
                failure_type="RESOLVED",
                resolved=True,
                valid_evaluation=True,
                started_at="2026-08-31T00:00:00+00:00",
                duration_ms=1,
            ).model_dump_json(indent=2),
            encoding="utf-8",
        )

        lines = render_cli_demo(run_path, report_path)

        assert lines[:4] == [
            "[SEARCH] parser",
            "[READ] src/parser.py",
            "[PATCH] apply_patch",
            "[TEST] tests/test_parser.py",
        ]
        assert lines[-1] == "[EVAL] RESOLVED"
        assert str((run_path / "final.patch").resolve()) in lines[-2]
    finally:
        shutil.rmtree(root)
