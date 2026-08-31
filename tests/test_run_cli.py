from __future__ import annotations

import sys
from pathlib import Path

import pytest

from evodev import run
from evodev.benchmark import BenchmarkLoader


def test_single_task_path_must_resolve_to_frozen_benchmark_task() -> None:
    loader = BenchmarkLoader(Path("benchmarks"))

    task = run._resolve_task(loader, Path("benchmarks/test/task_010"))

    assert task.config.task_id == "task_010"
    with pytest.raises(ValueError, match="frozen Benchmark task"):
        run._resolve_task(loader, Path("benchmarks/test/task_010/repo"))


def test_single_task_cli_checks_paid_confirmation_before_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evodev-run",
            "--task",
            "benchmarks/test/task_010",
            "--policy",
            "policy-v002",
        ],
    )
    monkeypatch.setattr(
        run,
        "load_settings",
        lambda *_: pytest.fail("Settings must not load before paid confirmation"),
    )

    with pytest.raises(PermissionError, match="--confirm-paid"):
        run.main()
