from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from evodev.benchmark import BenchmarkQA, BenchmarkTask, BenchmarkTaskConfig

TRAIN_ROOT = Path("benchmarks-v2/train")
TRAIN_QA_PATH = Path("benchmarks-v2/train-qa.json")
PILOT_ROOT = Path("benchmarks-pilot-v2")


def _load_train_task(path: Path) -> BenchmarkTask:
    config = BenchmarkTaskConfig.model_validate(
        yaml.safe_load((path / "task.yaml").read_text(encoding="utf-8"))
    )
    return BenchmarkTask(
        split="train",
        config=config,
        task_path=path.resolve(),
        repository_path=(path / "repo").resolve(),
        public_tests_path=(path / "repo" / "tests").resolve(),
        hidden_target_tests_path=(path / "hidden_tests" / "target").resolve(),
        hidden_regression_tests_path=(path / "hidden_tests" / "regression").resolve(),
        gold_patch_path=(path / "gold.patch").resolve(),
    )


TASKS = [_load_train_task(path) for path in sorted(TRAIN_ROOT.glob("task_*"))]
TASKS_BY_ID = {task.config.task_id: task for task in TASKS}

PILOT_SOURCES = {
    "task_101": PILOT_ROOT / "train" / "task_101",
    "task_102": PILOT_ROOT / "train" / "task_102",
    "task_103": PILOT_ROOT / "validation" / "task_103",
    "task_104": PILOT_ROOT / "test" / "task_104",
}

GOLD_REGRESSIONS = [
    pytest.param(
        "task_105",
        [("uploads/assembler.py", "if known_total is not None", "if False")],
        id="task_105-total-conflict-unchecked",
    ),
    pytest.param(
        "task_105",
        [("uploads/assembler.py", "if existing != chunk.data:", "if False:")],
        id="task_105-data-conflict-unchecked",
    ),
    pytest.param(
        "task_106",
        [
            (
                "billing/proration.py",
                "remaining_days = (subscription.period_end - effective_on).days + 1",
                "remaining_days = (subscription.period_end - effective_on).days",
            )
        ],
        id="task_106-exclusive-end-date",
    ),
    pytest.param(
        "task_106",
        [
            (
                "billing/proration.py",
                "price_difference_cents = _price_cents(new_plan) - _price_cents(old_plan)",
                "price_difference_cents = int(new_plan.monthly_price - old_plan.monthly_price)",
            )
        ],
        id="task_106-dollar-cent-mixup",
    ),
    pytest.param(
        "task_107",
        [
            (
                "parallelism/mapping.py",
                "results: list[OutputT | None] = [None] * len(values)",
                "results: list[OutputT | None] = []",
            ),
            (
                "parallelism/mapping.py",
                "results[positions[future]] = future.result()",
                "results.append(future.result())",
            ),
        ],
        id="task_107-completion-order-results",
    ),
    pytest.param(
        "task_107",
        [
            (
                "parallelism/mapping.py",
                "executor.shutdown(wait=True, cancel_futures=True)",
                "executor.shutdown(wait=True, cancel_futures=False)",
            )
        ],
        id="task_107-pending-work-not-cancelled",
    ),
    pytest.param(
        "task_108",
        [
            (
                "transport/adapter.py",
                "return send(method, url, headers, timeout)",
                (
                    "return send(\n"
                    "            method=method, url=url, headers=headers, timeout=timeout\n"
                    "        )"
                ),
            )
        ],
        id="task_108-keyword-only-without-legacy-adapter",
    ),
    pytest.param(
        "task_108",
        [
            (
                "transport/adapter.py",
                "if [parameter.name for parameter in parameters] != expected_names:",
                "if False:",
            )
        ],
        id="task_108-unsupported-signature-not-prevalidated",
    ),
]


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _pytest_environment() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


def _run_pytest(workspace: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            *paths,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_pytest_environment(),
        timeout=30,
        check=False,
    )


def test_formal_v2_train_inventory_and_pilot_migration() -> None:
    qa = json.loads(TRAIN_QA_PATH.read_text(encoding="utf-8"))
    assert [task.config.task_id for task in TASKS] == [
        f"task_{number}" for number in range(101, 109)
    ]
    assert Counter(task.config.category for task in TASKS) == {
        "cross_module_bug": 2,
        "state_data_flow": 2,
        "feature": 1,
        "error_resilience": 1,
        "concurrency_resource": 1,
        "test_repair_compatibility": 1,
    }
    assert len({task.config.repository_template for task in TASKS}) == 8
    assert all(task.config.benchmark_version == "2.0" for task in TASKS)
    assert all(task.config.difficulty in {"medium", "hard"} for task in TASKS)
    assert qa["stage"] == "train_qualified"
    assert qa["formal_manifest_created"] is False
    assert qa["qa"] == {
        "independent_rounds": 5,
        "public_original_passed": 8,
        "hidden_original_failed": 8,
        "hidden_gold_passed": 8,
        "new_task_incomplete_fixes_rejected": 8,
    }
    assert {entry["task_id"]: entry["checksum"] for entry in qa["tasks"]} == {
        task.config.task_id: _tree_digest(task.task_path) for task in TASKS
    }
    for task_id, source in PILOT_SOURCES.items():
        assert _tree_digest(TRAIN_ROOT / task_id) == _tree_digest(source)


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_formal_v2_train_public_tests_pass_original(task: BenchmarkTask) -> None:
    completed = _run_pytest(task.repository_path, "tests")

    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_formal_v2_train_original_fails_and_gold_passes(task: BenchmarkTask) -> None:
    result = BenchmarkQA().validate_task(task)

    assert result.original_failed is True
    assert result.gold_passed is True, result.after_output
    assert result.valid is True


@pytest.mark.parametrize(("task_id", "replacements"), GOLD_REGRESSIONS)
def test_new_train_hidden_tests_reject_incomplete_gold_regressions(
    tmp_path: Path,
    task_id: str,
    replacements: list[tuple[str, str, str]],
) -> None:
    task = TASKS_BY_ID[task_id]
    workspace = tmp_path / task_id
    shutil.copytree(task.repository_path, workspace)
    subprocess.run(
        ["git", "init", "-q"], cwd=workspace, capture_output=True, check=True
    )
    applied = subprocess.run(
        ["git", "apply", str(task.gold_patch_path)],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    for relative_path, old, new in replacements:
        path = workspace / relative_path
        content = path.read_text(encoding="utf-8")
        assert old in content
        path.write_text(content.replace(old, new, 1), encoding="utf-8")
    hidden = workspace / "hidden_eval"
    shutil.copytree(task.hidden_target_tests_path, hidden / "target")
    shutil.copytree(task.hidden_regression_tests_path, hidden / "regression")

    completed = _run_pytest(workspace, "hidden_eval/target", "hidden_eval/regression")

    assert completed.returncode != 0
