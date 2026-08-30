"""Disposable Git workspace lifecycle for one coding run."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class WorkspaceRun(BaseModel):
    """Resolved paths owned by one isolated coding run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    original_path: Path
    run_path: Path
    workspace_path: Path
    artifacts_path: Path


class WorkspaceManager:
    """Copy source repositories into isolated, resettable Git workspaces."""

    _ignored_names = frozenset(
        {".env", ".git", "__pycache__", ".pytest_cache", ".test_runtime"}
    )

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root.resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _remove_readonly(
        function: Callable[[str], object],
        path: str,
        _error_info: object,
    ) -> None:
        os.chmod(path, stat.S_IWRITE)
        function(path)

    @classmethod
    def _remove_tree(cls, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, onerror=cls._remove_readonly)

    @staticmethod
    def _git(workspace_path: Path, arguments: list[str]) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(detail or f"Git exited with code {completed.returncode}")
        return completed.stdout

    def _validate_run(self, run: WorkspaceRun) -> None:
        resolved_run = run.run_path.resolve()
        if resolved_run.parent != self.runs_root:
            raise ValueError("Run path is outside the configured runs root")
        if run.workspace_path.resolve() != resolved_run / "workspace":
            raise ValueError("Workspace path does not belong to the run")

    def create(self, original_path: Path, run_id: str | None = None) -> WorkspaceRun:
        """Create an independent copy and commit its baseline state."""
        source = original_path.resolve(strict=True)
        if not source.is_dir():
            raise NotADirectoryError(f"Original repository is not a directory: {source}")
        identifier = run_id or f"run_{uuid4().hex}"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("run_id contains unsupported characters")
        run_path = self.runs_root / identifier
        workspace_path = run_path / "workspace"
        artifacts_path = run_path / "artifacts"
        if run_path.exists():
            raise FileExistsError(f"Run already exists: {identifier}")

        excluded_root_name: str | None = None
        if self.runs_root.is_relative_to(source):
            excluded_root_name = self.runs_root.relative_to(source).parts[0]

        def ignore(directory: str, names: list[str]) -> set[str]:
            ignored = set(names) & self._ignored_names
            if Path(directory).resolve() == source and excluded_root_name in names:
                ignored.add(excluded_root_name)
            return ignored

        run_path.mkdir(parents=True)
        try:
            shutil.copytree(source, workspace_path, symlinks=True, ignore=ignore)
            artifacts_path.mkdir()
            for arguments in (
                ["init", "-q"],
                ["config", "user.email", "runs@evodev.local"],
                ["config", "user.name", "EvoDev Runs"],
                ["add", "."],
                ["commit", "-q", "-m", "workspace baseline"],
            ):
                self._git(workspace_path, arguments)
        except Exception:
            self._remove_tree(run_path)
            raise
        return WorkspaceRun(
            run_id=identifier,
            original_path=source,
            run_path=run_path,
            workspace_path=workspace_path,
            artifacts_path=artifacts_path,
        )

    def reset(self, run: WorkspaceRun) -> None:
        """Restore the workspace to its committed baseline."""
        self._validate_run(run)
        self._git(run.workspace_path, ["reset", "--hard", "HEAD"])
        self._git(run.workspace_path, ["clean", "-fdx"])

    def cleanup(
        self,
        run: WorkspaceRun,
        redact: Callable[[str], str] | None = None,
    ) -> None:
        """Remove only the disposable workspace, preserving run artifacts."""
        self._validate_run(run)
        final_diff = self._git(run.workspace_path, ["diff", "--no-ext-diff", "--"])
        persisted_diff = redact(final_diff) if redact is not None else final_diff
        (run.run_path / "final.patch").write_text(persisted_diff, encoding="utf-8")
        (run.run_path / "final.diff").write_text(persisted_diff, encoding="utf-8")
        self._remove_tree(run.workspace_path)

    def discard(self, run: WorkspaceRun) -> None:
        """Remove a disposable workspace without persisting evaluator-private files."""
        self._validate_run(run)
        self._remove_tree(run.workspace_path)
