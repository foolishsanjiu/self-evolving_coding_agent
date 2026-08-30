from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from evodev.benchmark import BenchmarkLoader, BenchmarkQA
from evodev.sandbox import WorkspaceManager

BENCHMARK_ROOT = Path("benchmarks")
LOADER = BenchmarkLoader(BENCHMARK_ROOT)
TASKS = LOADER.load_tasks()


def test_v1_inventory_has_frozen_size_splits_and_categories() -> None:
    assert len(TASKS) == 12
    assert Counter(task.split for task in TASKS) == {
        "train": 6,
        "validation": 3,
        "test": 3,
    }
    assert Counter(task.config.category for task in TASKS) == {
        "bug_fix": 4,
        "exception_handling": 2,
        "feature": 2,
        "refactoring": 2,
        "test_repair": 2,
    }


def test_manifest_matches_every_frozen_task_checksum() -> None:
    manifest = LOADER.verify_manifest()

    assert manifest.task_count == 12
    assert len({entry.checksum for entry in manifest.tasks}) == 12
    assert len(manifest.manifest_hash) == 64


def test_repository_template_cannot_cross_splits() -> None:
    duplicate = TASKS[6].model_copy(
        update={
            "config": TASKS[6].config.model_copy(
                update={"repository_template": TASKS[0].config.repository_template}
            )
        }
    )

    with pytest.raises(ValueError, match="cross benchmark splits"):
        LOADER._validate_inventory([*TASKS[:6], duplicate, *TASKS[7:]])


def test_agent_workspace_contains_only_public_repository(tmp_path: Path) -> None:
    task = TASKS[0]
    run = LOADER.create_agent_workspace(
        task,
        WorkspaceManager(tmp_path / "runs"),
        run_id="benchmark_isolation",
    )
    visible = {
        path.relative_to(run.workspace_path).as_posix()
        for path in run.workspace_path.rglob("*")
    }

    assert "pricing.py" in visible
    assert "tests/test_pricing.py" in visible
    assert "task.yaml" not in visible
    assert not any("hidden" in path for path in visible)
    assert not any("gold.patch" in path for path in visible)


def test_task_spec_exposes_public_metadata_only(tmp_path: Path) -> None:
    task = TASKS[0]
    spec = LOADER.to_task_spec(task, tmp_path)

    assert spec.task_id == "task_001"
    assert spec.metadata["split"] == "train"
    assert "hidden" not in str(spec.model_dump())
    assert "gold" not in str(spec.model_dump())


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_original_fails_and_gold_passes(task) -> None:
    result = BenchmarkQA().validate_task(task)

    assert result.original_failed is True
    assert result.gold_passed is True
    assert result.valid is True
