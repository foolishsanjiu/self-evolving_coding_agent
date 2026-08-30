"""Automated before-fail / after-gold-pass benchmark qualification."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from evodev.benchmark.models import BenchmarkQAResult, BenchmarkTask


class BenchmarkQA:
    """Validate task discriminative power without exposing evaluator assets."""

    def __init__(self, work_root: Path | None = None) -> None:
        self.work_root = (work_root or Path(".test_runtime") / "benchmark_qa").resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _run_hidden(workspace: Path) -> subprocess.CompletedProcess[str]:
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

    @staticmethod
    def _apply_gold(workspace: Path, patch_path: Path) -> None:
        for arguments in (["apply", "--check", str(patch_path)], ["apply", str(patch_path)]):
            completed = subprocess.run(
                ["git", *arguments],
                cwd=workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(f"Gold patch failed for {workspace.name}: {detail}")

    def validate_task(self, task: BenchmarkTask) -> BenchmarkQAResult:
        with TemporaryDirectory(
            prefix=f"evodev-{task.config.task_id}-",
            dir=self.work_root,
        ) as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(task.repository_path, workspace)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=workspace,
                capture_output=True,
                check=True,
            )
            hidden = workspace / "hidden_eval"
            shutil.copytree(task.hidden_target_tests_path, hidden / "target")
            shutil.copytree(task.hidden_regression_tests_path, hidden / "regression")
            before = self._run_hidden(workspace)
            self._apply_gold(workspace, task.gold_patch_path)
            after = self._run_hidden(workspace)
        before_output = before.stdout + before.stderr
        after_output = after.stdout + after.stderr
        original_failed = before.returncode != 0
        gold_passed = after.returncode == 0
        return BenchmarkQAResult(
            task_id=task.config.task_id,
            before_exit_code=before.returncode,
            after_exit_code=after.returncode,
            before_output=before_output,
            after_output=after_output,
            original_failed=original_failed,
            gold_passed=gold_passed,
            valid=original_failed and gold_passed,
        )

    def validate_all(self, tasks: list[BenchmarkTask]) -> list[BenchmarkQAResult]:
        results = [self.validate_task(task) for task in tasks]
        invalid = [result.task_id for result in results if not result.valid]
        if invalid:
            raise ValueError(f"Benchmark QA failed: {invalid}")
        return results
