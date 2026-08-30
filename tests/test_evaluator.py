from __future__ import annotations

import csv
import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from evodev.agent.events import AgentEvent
from evodev.benchmark import BenchmarkLoader
from evodev.config import SandboxSettings
from evodev.evaluation import (
    EvaluationGrades,
    EvaluationRequest,
    EvaluationResult,
    ExperimentManifest,
    ExperimentReporter,
    FailureType,
    IndependentEvaluator,
    TrajectoryMetricReader,
)
from evodev.sandbox import WorkspaceManager
from evodev.trajectory import RunMetadata, TrajectoryRecorder
from evodev.trajectory.models import utc_now

BENCHMARK_ROOT = Path("benchmarks")
IMAGE = "evodev-python:3.11"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    for command in (["docker", "info"], ["docker", "image", "inspect", IMAGE]):
        try:
            completed = subprocess.run(command, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if completed.returncode != 0:
            return False
    return True


@pytest.fixture
def evaluation_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"evaluator_{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _evaluator(root: Path) -> IndependentEvaluator:
    return IndependentEvaluator(
        BenchmarkLoader(BENCHMARK_ROOT),
        WorkspaceManager(root / "workspaces"),
        SandboxSettings(test_timeout_seconds=15),
    )


GOLD_PATCH = Path("benchmarks/train/task_001/gold.patch").read_text(encoding="utf-8")
INVALID_PATCH = "this is not a unified diff"
SYNTAX_PATCH = """\
diff --git a/pricing.py b/pricing.py
--- a/pricing.py
+++ b/pricing.py
@@ -1,2 +1,2 @@
 def discounted_price(price: float, discount_percent: float) -> float:
-    return price - discount_percent
+    return (
"""
REGRESSION_PATCH = """\
diff --git a/pricing.py b/pricing.py
--- a/pricing.py
+++ b/pricing.py
@@ -1,2 +1,4 @@
 def discounted_price(price: float, discount_percent: float) -> float:
-    return price - discount_percent
+    if discount_percent == 0:
+        return 0
+    return price * (1 - discount_percent / 100)
"""


@pytest.mark.skipif(not _docker_ready(), reason="Docker sandbox image is required")
@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (GOLD_PATCH, FailureType.RESOLVED),
        ("", FailureType.NO_PATCH),
        (INVALID_PATCH, FailureType.PATCH_APPLY_FAILED),
        (SYNTAX_PATCH, FailureType.SYNTAX_ERROR),
        (REGRESSION_PATCH, FailureType.REGRESSION_FAILED),
    ],
)
def test_required_independent_evaluation_cases(
    evaluation_root: Path,
    patch: str,
    expected: FailureType,
) -> None:
    original = Path("benchmarks/train/task_001/repo/pricing.py").read_text(encoding="utf-8")
    instance = evaluation_root / "instances" / expected.value.lower()
    result = _evaluator(evaluation_root).evaluate(
        EvaluationRequest(task_id="task_001", final_patch=patch, agent_run_id="run_001"),
        instance,
    )

    assert result.failure_type == expected
    assert result.resolved is (expected == FailureType.RESOLVED)
    assert (instance / "report.json").is_file()
    assert (instance / "final.patch").read_text(encoding="utf-8") == patch
    assert (instance / "test_output.txt").is_file()
    assert json.loads((instance / "trajectory_ref.json").read_text())["agent_run_id"] == (
        "run_001"
    )
    assert Path("benchmarks/train/task_001/repo/pricing.py").read_text(encoding="utf-8") == (
        original
    )


def test_evaluator_request_rejects_agent_self_report() -> None:
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(
            {
                "task_id": "task_001",
                "final_patch": GOLD_PATCH,
                "agent_run_id": "run_001",
                "agent_final_answer": "all tests pass",
            }
        )


def _metadata(run_id: str) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        task_id="task_001",
        agent_release="0.1.0",
        policy_version="policy-v0",
        policy_hash="none",
        experience_version="none",
        experience_hash="none",
        model="fake",
        temperature=0,
        prompt_version="v1",
        max_steps=15,
        context_budget=60_000,
        tool_provider="fake",
        tool_catalog_hash="a" * 64,
        benchmark_version="1.0",
        benchmark_hash="b" * 64,
        sandbox_image=IMAGE,
        sandbox_digest="c" * 64,
    )


def test_trajectory_metrics_and_experiment_outputs(evaluation_root: Path) -> None:
    run_id = "run_metrics"
    run_path = evaluation_root / "runs" / run_id
    recorder = TrajectoryRecorder(run_path, _metadata(run_id))
    for event in (
        AgentEvent(type="RUN_STARTED", data={"task_id": "task_001"}),
        AgentEvent(
            type="MODEL_TURN",
            data={"step_count": 1, "input_tokens": 10, "output_tokens": 2},
        ),
        AgentEvent(
            type="TOOL_CALL",
            data={
                "tool_call": {
                    "call_id": "search-1",
                    "name": "search_code",
                    "arguments": {"query": "discount"},
                }
            },
        ),
        AgentEvent(
            type="TOOL_CALL",
            data={
                "tool_call": {
                    "call_id": "patch-1",
                    "name": "apply_patch",
                    "arguments": {"patch": "small"},
                }
            },
        ),
        AgentEvent(type="RUN_FINISHED", data={"status": "SUCCESS"}),
    ):
        recorder.emit(event)
    metric = TrajectoryMetricReader.read(run_path)
    assert metric.react_steps == 1
    assert metric.tool_calls == 2
    assert metric.tokens == 12
    assert metric.searched_before_edit is True
    assert metric.patch_attempts == 1

    result = EvaluationResult(
        task_id="task_001",
        agent_run_id=run_id,
        benchmark_version="1.0",
        benchmark_hash="b" * 64,
        grades=EvaluationGrades(
            patch_exists=True,
            patch_applies=True,
            syntax_valid=True,
            target_tests_pass=True,
            regression_tests_pass=True,
        ),
        failure_type=FailureType.RESOLVED,
        resolved=True,
        valid_evaluation=True,
        started_at=utc_now(),
        duration_ms=1,
    )
    manifest = ExperimentManifest(
        experiment_id="exp-test",
        experiment_version="test-v1",
        repetitions=1,
        agent_release="0.1.0",
        policy_version="policy-v0",
        policy_hash="none",
        experience_version="none",
        experience_hash="none",
        model="fake",
        temperature=0,
        prompt_version="v1",
        max_steps=15,
        context_budget=60_000,
        tool_provider="fake",
        tool_catalog_hash="a" * 64,
        sandbox_image=IMAGE,
        sandbox_digest="c" * 64,
        benchmark_version="1.0",
        benchmark_hash="b" * 64,
    )
    experiment_path = evaluation_root / "exp-test"
    summary = ExperimentReporter(experiment_path, manifest).summarize(
        [result], {run_id: run_path}
    )

    assert summary.resolution_rate == 1
    assert summary.average_tokens == 12
    assert summary.search_before_edit_rate == 1
    assert (experiment_path / "manifest.json").is_file()
    assert (experiment_path / "summary.json").is_file()
    assert (experiment_path / "summary.csv").is_file()


def test_frozen_baseline_snapshot_is_consistent() -> None:
    baseline = Path("baselines/exp-baseline-v1")
    manifest = ExperimentManifest.model_validate_json(
        (baseline / "manifest.json").read_text(encoding="utf-8")
    )
    summary = json.loads((baseline / "summary.json").read_text(encoding="utf-8"))
    with (baseline / "summary.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert manifest.experiment_version == "exp-baseline-v1"
    benchmark_hash = BenchmarkLoader(BENCHMARK_ROOT).verify_manifest().manifest_hash
    assert manifest.benchmark_hash == benchmark_hash
    assert len(rows) == summary["total_attempts"] == 12
    assert sum(row["resolved"] == "True" for row in rows) == summary["resolved_attempts"] == 9
    assert summary["resolution_rate"] == 0.75
