"""Schemas for the frozen EvoDev benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BenchmarkSplit = Literal["train", "validation", "test"]
TaskCategory = str
TaskDifficulty = Literal["easy", "medium", "hard"]


class BenchmarkDefinition(BaseModel):
    """Declared inventory contract for one versioned benchmark root."""

    model_config = ConfigDict(extra="forbid")

    benchmark_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    task_count: int = Field(gt=0)
    split_counts: dict[BenchmarkSplit, int]
    category_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_counts(self) -> BenchmarkDefinition:
        if set(self.split_counts) != {"train", "validation", "test"}:
            raise ValueError("Benchmark split_counts must declare train, validation, and test")
        if any(count < 1 for count in self.split_counts.values()):
            raise ValueError("Every Benchmark split must contain at least one task")
        if not self.category_counts or any(
            not category or count < 1
            for category, count in self.category_counts.items()
        ):
            raise ValueError("Benchmark categories must have non-empty names and positive counts")
        if sum(self.split_counts.values()) != self.task_count:
            raise ValueError("Benchmark split counts do not match task_count")
        if sum(self.category_counts.values()) != self.task_count:
            raise ValueError("Benchmark category counts do not match task_count")
        return self


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
    benchmark_version: str = Field(default="1.0", pattern=r"^[0-9]+\.[0-9]+$")


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

    benchmark_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    task_count: int = Field(gt=0)
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
