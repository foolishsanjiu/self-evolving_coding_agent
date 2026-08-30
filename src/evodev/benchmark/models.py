"""Schemas for the frozen EvoDev benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BenchmarkSplit = Literal["train", "validation", "test"]
TaskCategory = Literal[
    "bug_fix",
    "exception_handling",
    "feature",
    "refactoring",
    "test_repair",
]
TaskDifficulty = Literal["easy", "medium", "hard"]


class BenchmarkTaskConfig(BaseModel):
    """Public metadata loaded from one task.yaml file."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^task_[0-9]{3}$")
    category: TaskCategory
    difficulty: TaskDifficulty
    description: str = Field(min_length=1)
    test_command: Literal["pytest -q"] = "pytest -q"
    expected_behavior: str = Field(min_length=1)
    repository_template: str = Field(min_length=1)
    benchmark_version: Literal["1.0"] = "1.0"


class BenchmarkTask(BaseModel):
    """Resolved public and evaluator-only paths for one benchmark instance."""

    model_config = ConfigDict(extra="forbid")

    split: BenchmarkSplit
    config: BenchmarkTaskConfig
    task_path: Path
    repository_path: Path
    public_tests_path: Path
    hidden_target_tests_path: Path
    hidden_regression_tests_path: Path
    gold_patch_path: Path


class TaskManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    split: BenchmarkSplit
    category: TaskCategory
    repository_template: str
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class BenchmarkManifest(BaseModel):
    """Frozen benchmark inventory and integrity hashes."""

    model_config = ConfigDict(extra="forbid")

    benchmark_version: Literal["1.0"] = "1.0"
    task_count: Literal[12] = 12
    split_counts: dict[BenchmarkSplit, int]
    category_counts: dict[TaskCategory, int]
    tasks: list[TaskManifestEntry]
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BenchmarkQAResult(BaseModel):
    """Before-fail / after-gold-pass evidence for one task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    before_exit_code: int
    after_exit_code: int
    before_output: str
    after_output: str
    original_failed: bool
    gold_passed: bool
    valid: bool
