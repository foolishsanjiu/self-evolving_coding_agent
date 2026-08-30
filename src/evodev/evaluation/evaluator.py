"""Clean-workspace, Docker-backed independent patch evaluation."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from evodev.benchmark import BenchmarkLoader, BenchmarkTask
from evodev.config import SandboxSettings
from evodev.evaluation.models import (
    EvaluationGrades,
    EvaluationRequest,
    EvaluationResult,
    FailureType,
)
from evodev.sandbox import (
    DockerTestRunner,
    SandboxCleanupError,
    SandboxUnavailableError,
    WorkspaceManager,
)
from evodev.trajectory.models import utc_now

_SYNTAX_TEST = '''from pathlib import Path


def test_repository_python_syntax() -> None:
    failures = []
    for path in Path(".").rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            failures.append(f"{path}: {exc.msg} at line {exc.lineno}")
    assert not failures, "\\n".join(failures)
'''


class IndependentEvaluator:
    """Grade only a clean repository plus submitted patch and hidden tests."""

    def __init__(
        self,
        loader: BenchmarkLoader,
        workspace_manager: WorkspaceManager,
        sandbox_settings: SandboxSettings,
        trajectories_root: Path | None = None,
    ) -> None:
        self.loader = loader
        self.workspace_manager = workspace_manager
        self.sandbox_settings = sandbox_settings
        self.trajectories_root = trajectories_root.resolve() if trajectories_root else None
        self.manifest = loader.verify_manifest()
        self.tasks = {task.config.task_id: task for task in loader.load_tasks()}

    def _agent_failure(self, agent_run_id: str) -> FailureType | None:
        if self.trajectories_root is None:
            return None
        run_path = self.trajectories_root / agent_run_id
        metadata_path = run_path / "run.json"
        events_path = run_path / "events.jsonl"
        if not metadata_path.is_file():
            return None
        status = json.loads(metadata_path.read_text(encoding="utf-8")).get("status")
        if status == "MAX_STEPS":
            return FailureType.AGENT_MAX_STEPS
        if status == "ERROR":
            return FailureType.AGENT_ERROR
        if events_path.is_file():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                result = event.get("data", {}).get("result", {})
                if event.get("type") == "TOOL_RESULT" and result.get("success") is False:
                    return FailureType.AGENT_TOOL_FAILURE
        return None

    @staticmethod
    def _write_patch(path: Path, patch: str) -> str:
        canonical = patch.replace("\r\n", "\n")
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(canonical)
        return canonical

    @staticmethod
    def _apply_patch(workspace: Path, patch_path: Path) -> tuple[bool, str]:
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
                return False, detail
        return True, "Patch applied"

    @staticmethod
    def _install_hidden_tests(task: BenchmarkTask, workspace: Path) -> None:
        hidden_root = workspace / ".evodev_hidden"
        shutil.copytree(task.hidden_target_tests_path, hidden_root / "target")
        shutil.copytree(task.hidden_regression_tests_path, hidden_root / "regression")
        syntax_root = hidden_root / "syntax"
        syntax_root.mkdir()
        (syntax_root / "test_syntax.py").write_text(_SYNTAX_TEST, encoding="utf-8")

    @staticmethod
    def _stage_text(result: dict[str, object]) -> str:
        return f"{result.get('stdout', '')}{result.get('stderr', '')}"

    def _write_result(
        self,
        instance_path: Path,
        result: EvaluationResult,
        final_patch: str,
    ) -> EvaluationResult:
        instance_path.mkdir(parents=True, exist_ok=True)
        self._write_patch(instance_path / "final.patch", final_patch)
        (instance_path / "report.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        (instance_path / "test_output.txt").write_text(
            "\n\n".join(
                f"== {stage} ==\n{output}" for stage, output in result.stage_outputs.items()
            ),
            encoding="utf-8",
        )
        (instance_path / "trajectory_ref.json").write_text(
            json.dumps({"agent_run_id": result.agent_run_id}, indent=2),
            encoding="utf-8",
        )
        return result

    def evaluate(
        self,
        request: EvaluationRequest,
        instance_path: Path,
    ) -> EvaluationResult:
        """Evaluate a submitted patch without trusting Agent state or self-reports."""
        started_at = utc_now()
        started = time.perf_counter()
        task = self.tasks.get(request.task_id)
        if task is None:
            raise ValueError(f"Unknown benchmark task: {request.task_id}")
        output_path = instance_path.resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        patch_path = output_path / "final.patch"
        canonical_patch = self._write_patch(patch_path, request.final_patch)
        grades = EvaluationGrades(patch_exists=bool(request.final_patch.strip()))
        stage_outputs: dict[str, str] = {}

        def finish(failure: FailureType, *, valid: bool = True) -> EvaluationResult:
            result = EvaluationResult(
                task_id=request.task_id,
                agent_run_id=request.agent_run_id,
                benchmark_version=self.manifest.benchmark_version,
                benchmark_hash=self.manifest.manifest_hash,
                grades=grades,
                failure_type=failure,
                resolved=failure == FailureType.RESOLVED,
                valid_evaluation=valid,
                started_at=started_at,
                duration_ms=round((time.perf_counter() - started) * 1000),
                stage_outputs=stage_outputs,
            )
            return self._write_result(output_path, result, canonical_patch)

        if not grades.patch_exists:
            return finish(self._agent_failure(request.agent_run_id) or FailureType.NO_PATCH)

        run = self.workspace_manager.create(
            task.repository_path,
            run_id=f"eval_{request.task_id}_{uuid4().hex[:12]}",
        )
        try:
            applied, detail = self._apply_patch(run.workspace_path, patch_path)
            stage_outputs["patch_apply"] = detail
            if not applied:
                return finish(FailureType.PATCH_APPLY_FAILED)
            grades.patch_applies = True
            self._install_hidden_tests(task, run.workspace_path)
            runner = DockerTestRunner(self.sandbox_settings, output_path / "artifacts")
            for stage, test_path, grade_field, failure in (
                ("syntax", ".evodev_hidden/syntax", "syntax_valid", FailureType.SYNTAX_ERROR),
                (
                    "target",
                    ".evodev_hidden/target",
                    "target_tests_pass",
                    FailureType.TARGET_TEST_FAILED,
                ),
                (
                    "regression",
                    ".evodev_hidden/regression",
                    "regression_tests_pass",
                    FailureType.REGRESSION_FAILED,
                ),
            ):
                stage_result = runner.run_tests(run.workspace_path, test_path)
                stage_outputs[stage] = self._stage_text(stage_result)
                if bool(stage_result.get("timed_out")):
                    return finish(FailureType.EVALUATION_TIMEOUT, valid=False)
                if not bool(stage_result.get("passed")):
                    return finish(failure)
                setattr(grades, grade_field, True)
            return finish(FailureType.RESOLVED)
        except (SandboxUnavailableError, SandboxCleanupError, OSError) as exc:
            stage_outputs["environment"] = f"{type(exc).__name__}: {exc}"
            return finish(FailureType.ENVIRONMENT_ERROR, valid=False)
        finally:
            self.workspace_manager.discard(run)
