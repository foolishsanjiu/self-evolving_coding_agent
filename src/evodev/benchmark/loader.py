"""Strict loader, isolation bridge, and stable benchmark hashing."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from evodev.benchmark.models import (
    BenchmarkManifest,
    BenchmarkSplit,
    BenchmarkTask,
    BenchmarkTaskConfig,
    TaskManifestEntry,
)
from evodev.sandbox import WorkspaceManager, WorkspaceRun
from evodev.schemas import TaskSpec

EXPECTED_SPLITS = {"train": 6, "validation": 3, "test": 3}
EXPECTED_CATEGORIES = {
    "bug_fix": 4,
    "exception_handling": 2,
    "feature": 2,
    "refactoring": 2,
    "test_repair": 2,
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class BenchmarkLoader:
    """Load only valid v1.0 tasks and materialize public agent workspaces."""

    def __init__(self, benchmark_root: Path) -> None:
        self.root = benchmark_root.resolve(strict=True)

    @staticmethod
    def _files_exist(path: Path, pattern: str) -> bool:
        return path.is_dir() and any(path.rglob(pattern))

    def _load_task(self, split: BenchmarkSplit, task_path: Path) -> BenchmarkTask:
        config_path = task_path / "task.yaml"
        repository = (task_path / "repo").resolve(strict=True)
        public_tests = (repository / "tests").resolve(strict=True)
        hidden_target = (task_path / "hidden_tests" / "target").resolve(strict=True)
        hidden_regression = (task_path / "hidden_tests" / "regression").resolve(strict=True)
        gold_patch = (task_path / "gold.patch").resolve(strict=True)
        for private_path in (hidden_target, hidden_regression, gold_patch):
            if private_path.is_relative_to(repository):
                raise ValueError(
                    f"Private benchmark asset is inside agent repository: {private_path}"
                )
        if not self._files_exist(public_tests, "test_*.py"):
            raise ValueError(f"Public tests are missing: {task_path.name}")
        if not self._files_exist(hidden_target, "test_*.py"):
            raise ValueError(f"Hidden target tests are missing: {task_path.name}")
        if not self._files_exist(hidden_regression, "test_*.py"):
            raise ValueError(f"Hidden regression tests are missing: {task_path.name}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config = BenchmarkTaskConfig.model_validate(raw)
        if config.task_id != task_path.name:
            raise ValueError(f"Task directory and task_id differ: {task_path}")
        return BenchmarkTask(
            split=split,
            config=config,
            task_path=task_path,
            repository_path=repository,
            public_tests_path=public_tests,
            hidden_target_tests_path=hidden_target,
            hidden_regression_tests_path=hidden_regression,
            gold_patch_path=gold_patch,
        )

    def load_tasks(self) -> list[BenchmarkTask]:
        tasks: list[BenchmarkTask] = []
        for split in ("train", "validation", "test"):
            split_path = self.root / split
            if not split_path.is_dir():
                raise ValueError(f"Benchmark split is missing: {split}")
            tasks.extend(
                self._load_task(split, path)
                for path in sorted(split_path.glob("task_*"))
                if path.is_dir()
            )
        self._validate_inventory(tasks)
        return tasks

    @staticmethod
    def _validate_inventory(tasks: list[BenchmarkTask]) -> None:
        identifiers = [task.config.task_id for task in tasks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Benchmark task_id values must be unique")
        split_counts = Counter(task.split for task in tasks)
        category_counts = Counter(task.config.category for task in tasks)
        if dict(split_counts) != EXPECTED_SPLITS:
            raise ValueError(f"Expected split counts {EXPECTED_SPLITS}, got {dict(split_counts)}")
        if dict(category_counts) != EXPECTED_CATEGORIES:
            raise ValueError(
                f"Expected category counts {EXPECTED_CATEGORIES}, got {dict(category_counts)}"
            )
        template_splits: dict[str, set[str]] = defaultdict(set)
        for task in tasks:
            template_splits[task.config.repository_template].add(task.split)
        leaked = sorted(name for name, splits in template_splits.items() if len(splits) > 1)
        if leaked:
            raise ValueError(f"Repository templates cross benchmark splits: {leaked}")

    def build_manifest(self, tasks: list[BenchmarkTask] | None = None) -> BenchmarkManifest:
        loaded = tasks or self.load_tasks()
        entries = [
            TaskManifestEntry(
                task_id=task.config.task_id,
                split=task.split,
                category=task.config.category,
                repository_template=task.config.repository_template,
                checksum=_tree_hash(task.task_path),
            )
            for task in loaded
        ]
        payload = {
            "benchmark_version": "1.0",
            "task_count": len(entries),
            "split_counts": dict(Counter(task.split for task in loaded)),
            "category_counts": dict(Counter(task.config.category for task in loaded)),
            "tasks": [entry.model_dump(mode="json") for entry in entries],
        }
        return BenchmarkManifest(**payload, manifest_hash=_canonical_hash(payload))

    def load_manifest(self) -> BenchmarkManifest:
        return BenchmarkManifest.model_validate_json(
            (self.root / "manifest.json").read_text(encoding="utf-8")
        )

    def verify_manifest(self) -> BenchmarkManifest:
        stored = self.load_manifest()
        current = self.build_manifest()
        if stored != current:
            raise ValueError("Benchmark manifest does not match current task contents")
        return current

    @staticmethod
    def create_agent_workspace(
        task: BenchmarkTask,
        manager: WorkspaceManager,
        run_id: str | None = None,
    ) -> WorkspaceRun:
        return manager.create(task.repository_path, run_id=run_id)

    @staticmethod
    def to_task_spec(task: BenchmarkTask, workspace_path: Path) -> TaskSpec:
        return TaskSpec(
            task_id=task.config.task_id,
            instruction=task.config.description,
            workspace_path=workspace_path,
            metadata={
                "benchmark_version": task.config.benchmark_version,
                "split": task.split,
                "category": task.config.category,
                "difficulty": task.config.difficulty,
                "expected_behavior": task.config.expected_behavior,
                "repository_template": task.config.repository_template,
            },
        )
