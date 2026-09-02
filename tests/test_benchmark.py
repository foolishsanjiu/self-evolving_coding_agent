from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from evodev.benchmark import BenchmarkLoader, BenchmarkQA
from evodev.sandbox import WorkspaceManager

BENCHMARK_ROOT = Path("benchmarks")
V2_BLUEPRINT_PATH = Path("configs/benchmarks/v2-blueprint.yaml")
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
    assert manifest.manifest_hash == (
        "5d22632e017efeea07cde1f52c948aca03337df6314f6289e2393aec2558b453"
    )


def test_declared_v2_inventory_is_not_limited_to_v1_counts(tmp_path: Path) -> None:
    definition = {
        "benchmark_version": "2.0",
        "task_count": 18,
        "split_counts": {"train": 8, "validation": 5, "test": 5},
        "category_counts": {
            "cross_module_bug": 4,
            "state_data_flow": 3,
            "feature": 3,
            "error_resilience": 3,
            "concurrency_resource": 2,
            "test_repair_compatibility": 3,
        },
    }
    (tmp_path / "benchmark.yaml").write_text(
        yaml.safe_dump(definition, sort_keys=False), encoding="utf-8"
    )
    loader = BenchmarkLoader(tmp_path)
    splits = ["train"] * 8 + ["validation"] * 5 + ["test"] * 5
    categories = [
        "cross_module_bug",
    ] * 4 + [
        "state_data_flow",
    ] * 3 + [
        "feature",
    ] * 3 + [
        "error_resilience",
    ] * 3 + [
        "concurrency_resource",
    ] * 2 + [
        "test_repair_compatibility",
    ] * 3
    tasks = []
    for number, (split, category) in enumerate(zip(splits, categories), start=101):
        config = TASKS[0].config.model_copy(
            update={
                "task_id": f"task_{number}",
                "category": category,
                "repository_template": f"v2_template_{number}",
                "benchmark_version": "2.0",
            }
        )
        tasks.append(TASKS[0].model_copy(update={"split": split, "config": config}))

    loader._validate_inventory(tasks)


def test_v2_blueprint_freezes_inventory_and_leakage_boundaries() -> None:
    blueprint = yaml.safe_load(V2_BLUEPRINT_PATH.read_text(encoding="utf-8"))
    tasks = blueprint["tasks"]
    split_counts = Counter(task["split"] for task in tasks)
    category_counts = Counter(task["category"] for task in tasks)

    assert blueprint["status"] == "benchmark_frozen"
    assert blueprint["implementation_stage"] == "formal_frozen"
    assert blueprint["inventory"]["task_count"] == len(tasks) == 18
    assert split_counts == blueprint["inventory"]["split_counts"]
    assert category_counts == blueprint["inventory"]["category_counts"]
    assert [task["task_id"] for task in tasks] == [
        f"task_{number}" for number in range(101, 119)
    ]
    assert {task["difficulty"] for task in tasks} <= {"medium", "hard"}
    assert len({task["repository_template"] for task in tasks}) == 18
    assert not ({task.config.repository_template for task in TASKS} & {
        task["repository_template"] for task in tasks
    })

    pilots = [task for task in tasks if task["source"] == "pilot_calibrated"]
    assert [task["task_id"] for task in pilots] == [
        "task_101",
        "task_102",
        "task_103",
        "task_104",
    ]
    assert all(task["split"] == "train" for task in pilots)
    assert all(task["implementation_status"] == "migrated_train_qa" for task in pilots)
    assert all(task["prior_agent_runs"] is True for task in pilots)

    formal_train = [task for task in tasks if task["split"] == "train"]
    assert {task["implementation_status"] for task in formal_train} == {
        "migrated_train_qa",
        "implemented_train_qa",
    }

    formal_validation = [task for task in tasks if task["split"] == "validation"]
    assert {task["implementation_status"] for task in formal_validation} == {
        "implemented_validation_qa"
    }

    formal_test = [task for task in tasks if task["split"] == "test"]
    assert {task["implementation_status"] for task in formal_test} == {
        "implemented_test_qa"
    }

    unseen = [task for task in tasks if task["split"] in {"validation", "test"}]
    assert len(unseen) == 10
    assert all(task["source"] == "new_unseen" for task in unseen)
    assert all(task["prior_agent_runs"] is False for task in unseen)
    assert all(task["calibration_experiment_id"] is None for task in unseen)
    assert {task["evaluation_usage"] for task in unseen if task["split"] == "validation"} == {
        "policy_gate_only"
    }
    assert {task["evaluation_usage"] for task in unseen if task["split"] == "test"} == {
        "final_only"
    }
    assert all(len(task["hidden_target_focus"]) >= 2 for task in tasks)
    assert all(len(task["regression_focus"]) >= 2 for task in tasks)
    assert all(task["failure_mechanism"] and task["gold_scope"] for task in tasks)


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
