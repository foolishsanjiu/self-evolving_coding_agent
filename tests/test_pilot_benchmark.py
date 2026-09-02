import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evodev.benchmark import BenchmarkLoader, BenchmarkQA

PILOT_ROOT = Path("benchmarks-pilot-v2")
PILOT_EXPERIMENT_ROOT = Path("experiments/benchmark-v2-pilot-v1")
LOADER = BenchmarkLoader(PILOT_ROOT)
TASKS = LOADER.load_tasks()
TASKS_BY_ID = {task.config.task_id: task for task in TASKS}

NEGATIVE_MUTATIONS = [
    pytest.param(
        "task_101",
        [
            (
                "catalog/service.py",
                "self.cache.get(product_id)",
                'self.cache.get(f"{product_id}:{locale}")',
            ),
            (
                "catalog/service.py",
                "self.cache.put(product_id, view)",
                'self.cache.put(f"{product_id}:{locale}", view)',
            ),
        ],
        id="task_101-locale-only-key",
    ),
    pytest.param(
        "task_101",
        [
            (
                "catalog/service.py",
                "self.cache.get(product_id)",
                'self.cache.get(f"{product_id}:{include_tax}")',
            ),
            (
                "catalog/service.py",
                "self.cache.put(product_id, view)",
                'self.cache.put(f"{product_id}:{include_tax}", view)',
            ),
        ],
        id="task_101-tax-only-key",
    ),
    pytest.param(
        "task_102",
        [
            (
                "paging/service.py",
                "cursor = page.items[-1].item_id if page.items else None",
                "cursor = page.next_cursor if page.items else None",
            )
        ],
        id="task_102-empty-page-still-broken",
    ),
    pytest.param(
        "task_102",
        [
            (
                "paging/service.py",
                "cursor = page.items[-1].item_id if page.items else None",
                (
                    "cursor = (\n"
                    "            page.next_cursor if not page.items else page.items[-1].item_id\n"
                    "        )"
                ),
            )
        ],
        id="task_102-item-derived-cursor-remains",
    ),
    pytest.param(
        "task_103",
        [
            (
                "settings/resolver.py",
                "for source in (cli, file_values, environment, DEFAULTS):",
                "for source in (cli, environment, file_values, DEFAULTS):",
            )
        ],
        id="task_103-precedence-only",
    ),
    pytest.param(
        "task_103",
        [
            (
                "settings/coercion.py",
                "return bool(value)",
                'return str(value).strip().lower() in {"1", "true", "yes", "on"}',
            )
        ],
        id="task_103-boolean-only",
    ),
    pytest.param(
        "task_104",
        [
            (
                "inventory/service.py",
                "from inventory.models import OrderLine",
                (
                    "from inventory.errors import InsufficientStockError\n"
                    "from inventory.models import OrderLine"
                ),
            ),
            (
                "inventory/service.py",
                (
                    "    for line in lines:\n"
                    "        store.reserve(line.sku, line.quantity)"
                ),
                (
                    "    reserved: list[OrderLine] = []\n"
                    "    try:\n"
                    "        for line in lines:\n"
                    "            store.reserve(line.sku, line.quantity)\n"
                    "            reserved.append(line)\n"
                    "    except InsufficientStockError:\n"
                    "        for line in reversed(reserved):\n"
                    "            store.release(line.sku, line.quantity)\n"
                    "        raise"
                ),
            ),
        ],
        id="task_104-stock-errors-only",
    ),
    pytest.param(
        "task_104",
        [
            (
                "inventory/service.py",
                (
                    "    for line in lines:\n"
                    "        store.reserve(line.sku, line.quantity)"
                ),
                (
                    "    last_reserved: OrderLine | None = None\n"
                    "    try:\n"
                    "        for line in lines:\n"
                    "            store.reserve(line.sku, line.quantity)\n"
                    "            last_reserved = line\n"
                    "    except Exception:\n"
                    "        if last_reserved is not None:\n"
                    "            store.release(last_reserved.sku, last_reserved.quantity)\n"
                    "        raise"
                ),
            )
        ],
        id="task_104-last-line-only",
    ),
]


def test_pilot_inventory_and_manifest_are_frozen() -> None:
    manifest = LOADER.verify_manifest()

    assert manifest.benchmark_version == "2.0"
    assert manifest.task_count == 4
    assert manifest.split_counts == {"train": 2, "validation": 1, "test": 1}
    assert {task.config.difficulty for task in TASKS} <= {"medium", "hard"}
    assert len({task.config.repository_template for task in TASKS}) == 4


def test_paid_pilot_summary_matches_frozen_plan() -> None:
    manifest = json.loads(
        (PILOT_EXPERIMENT_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (PILOT_EXPERIMENT_ROOT / "summary.json").read_text(encoding="utf-8")
    )
    with (PILOT_EXPERIMENT_ROOT / "summary.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))

    planned_ids = {
        run_id for variant in manifest["variants"] for run_id in variant["run_ids"]
    }
    assert manifest["benchmark"]["manifest_hash"] == LOADER.verify_manifest().manifest_hash
    assert manifest["paid_agent_calls"] == 8
    assert manifest["selective_reruns"] is False
    assert len(rows) == len(planned_ids) == 8
    assert {row["run_id"] for row in rows} == planned_ids
    assert all(row["valid_evaluation"] == "true" for row in rows)
    assert sum(row["resolved"] == "true" for row in rows) == 3
    assert sum(int(row["total_tokens"]) for row in rows) == 651625
    assert summary["variants"]["baseline"]["resolved"] == 2
    assert summary["variants"]["champion"]["resolved"] == 1


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_pilot_original_fails_and_gold_passes(task) -> None:
    result = BenchmarkQA().validate_task(task)

    assert result.original_failed is True
    assert result.gold_passed is True
    assert result.valid is True


@pytest.mark.parametrize(("task_id", "replacements"), NEGATIVE_MUTATIONS)
def test_pilot_hidden_tests_reject_incomplete_fixes(
    tmp_path: Path,
    task_id: str,
    replacements: list[tuple[str, str, str]],
) -> None:
    task = TASKS_BY_ID[task_id]
    workspace = tmp_path / task_id
    shutil.copytree(task.repository_path, workspace)
    hidden = workspace / "hidden_eval"
    shutil.copytree(task.hidden_target_tests_path, hidden / "target")
    shutil.copytree(task.hidden_regression_tests_path, hidden / "regression")
    for relative_path, old, new in replacements:
        path = workspace / relative_path
        content = path.read_text(encoding="utf-8")
        assert old in content
        path.write_text(content.replace(old, new, 1), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "hidden_eval/target",
            "hidden_eval/regression",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
