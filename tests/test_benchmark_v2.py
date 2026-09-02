from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from evodev.benchmark import BenchmarkLoader
from evodev.sandbox import WorkspaceManager

BENCHMARK_ROOT = Path("benchmarks-v2")
BLUEPRINT_PATH = Path("configs/benchmarks/v2-blueprint.yaml")
FORMAL_QA_PATH = BENCHMARK_ROOT / "formal-qa.json"
SPLIT_QA_PATHS = [
    BENCHMARK_ROOT / "train-qa.json",
    BENCHMARK_ROOT / "validation-qa.json",
    BENCHMARK_ROOT / "test-qa.json",
]
LOADER = BenchmarkLoader(BENCHMARK_ROOT)
TASKS = LOADER.load_tasks()


def test_formal_v2_manifest_matches_complete_inventory() -> None:
    manifest = LOADER.verify_manifest()

    assert manifest.benchmark_version == "2.0"
    assert manifest.manifest_hash == (
        "c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6"
    )
    assert manifest.task_count == len(TASKS) == 18
    assert manifest.split_counts == {"train": 8, "validation": 5, "test": 5}
    assert manifest.category_counts == {
        "cross_module_bug": 4,
        "state_data_flow": 3,
        "feature": 3,
        "error_resilience": 3,
        "concurrency_resource": 2,
        "test_repair_compatibility": 3,
    }
    assert [task.config.task_id for task in TASKS] == [
        f"task_{number}" for number in range(101, 119)
    ]
    assert len({entry.checksum for entry in manifest.tasks}) == 18
    assert len({entry.repository_template for entry in manifest.tasks}) == 18


def test_formal_manifest_is_covered_by_split_qa_records() -> None:
    manifest = LOADER.verify_manifest()
    formal_qa = json.loads(FORMAL_QA_PATH.read_text(encoding="utf-8"))
    split_records = [
        json.loads(path.read_text(encoding="utf-8")) for path in SPLIT_QA_PATHS
    ]
    recorded_checksums = {
        task["task_id"]: task["checksum"]
        for record in split_records
        for task in record["tasks"]
    }

    assert formal_qa["stage"] == "formal_frozen"
    assert formal_qa["formal_manifest_created"] is True
    assert formal_qa["manifest_hash"] == manifest.manifest_hash
    assert formal_qa["freeze_agent_runs"] == 0
    assert formal_qa["freeze_paid_calls"] == 0
    assert formal_qa["qa"]["split_records_verified"] == len(split_records) == 3
    assert formal_qa["qa"]["task_checksums_verified"] == len(recorded_checksums) == 18
    assert formal_qa["qa"]["unified_benchmark_qa_rounds"] == 1
    assert formal_qa["qa"]["unified_hidden_original_failed"] == 18
    assert formal_qa["qa"]["unified_hidden_gold_passed"] == 18
    assert recorded_checksums == {
        entry.task_id: entry.checksum for entry in manifest.tasks
    }
    assert all(record["formal_manifest_created"] is False for record in split_records)
    assert formal_qa["qa"]["independent_split_rounds"] == {
        "train": 5,
        "validation": 5,
        "test": 5,
    }


def test_formal_v2_blueprint_matches_frozen_manifest() -> None:
    manifest = LOADER.verify_manifest()
    blueprint = yaml.safe_load(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    blueprint_tasks = blueprint["tasks"]

    assert blueprint["status"] == "benchmark_frozen"
    assert blueprint["implementation_stage"] == "formal_frozen"
    assert blueprint["inventory"]["task_count"] == manifest.task_count
    assert blueprint["inventory"]["split_counts"] == manifest.split_counts
    assert blueprint["inventory"]["category_counts"] == manifest.category_counts
    assert Counter(task["split"] for task in blueprint_tasks) == manifest.split_counts
    assert Counter(task["category"] for task in blueprint_tasks) == (
        manifest.category_counts
    )
    assert {
        (
            task["task_id"],
            task["split"],
            task["category"],
            task["repository_template"],
        )
        for task in blueprint_tasks
    } == {
        (entry.task_id, entry.split, entry.category, entry.repository_template)
        for entry in manifest.tasks
    }
    assert all(task["implementation_status"] != "planned" for task in blueprint_tasks)


def test_every_agent_workspace_excludes_private_assets(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "runs")

    for task in TASKS:
        run = LOADER.create_agent_workspace(
            task,
            manager,
            run_id=f"isolation_{task.config.task_id}",
        )
        visible = {
            path.relative_to(run.workspace_path).as_posix()
            for path in run.workspace_path.rglob("*")
        }
        assert any(path.startswith("tests/test_") for path in visible)
        assert "task.yaml" not in visible
        assert not any("hidden" in path for path in visible)
        assert "gold.patch" not in visible


def test_every_task_spec_exposes_only_public_metadata(tmp_path: Path) -> None:
    for task in TASKS:
        spec = LOADER.to_task_spec(task, tmp_path / task.config.task_id)

        assert spec.task_id == task.config.task_id
        assert spec.metadata == {
            "benchmark_version": "2.0",
            "split": task.split,
            "category": task.config.category,
            "difficulty": task.config.difficulty,
            "expected_behavior": task.config.expected_behavior,
            "repository_template": task.config.repository_template,
        }
        assert "hidden" not in str(spec.model_dump()).lower()
        assert "gold.patch" not in str(spec.model_dump()).lower()
