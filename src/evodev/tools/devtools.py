"""Workspace-bound implementations shared by Native and future MCP tools."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class PathOutsideWorkspaceError(ValueError):
    """Raised when a requested path escapes the configured workspace."""


class PatchApplyError(RuntimeError):
    """Raised when a unified diff is invalid or cannot be applied."""


class GitOperationError(RuntimeError):
    """Raised when a required Git operation fails."""


class InvalidTestSelectionError(ValueError):
    """Raised when a test path or selector is outside the controlled pytest grammar."""


class DevToolsService:
    """Development tools constrained to one workspace root."""

    def __init__(
        self,
        workspace_path: Path,
        test_timeout_seconds: float = 60,
        max_output_chars: int = 20_000,
        max_diff_chars: int = 20_000,
    ) -> None:
        self.workspace_path = workspace_path.resolve(strict=True)
        if not self.workspace_path.is_dir():
            raise NotADirectoryError(f"Workspace is not a directory: {workspace_path}")
        if test_timeout_seconds <= 0:
            raise ValueError("test_timeout_seconds must be positive")
        self.test_timeout_seconds = test_timeout_seconds
        self.max_output_chars = max_output_chars
        self.max_diff_chars = max_diff_chars

    def _resolve_path(self, requested_path: str) -> Path:
        path = Path(requested_path)
        candidate = path if path.is_absolute() else self.workspace_path / path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace_path)
        except ValueError as exc:
            raise PathOutsideWorkspaceError(
                f"Path is outside workspace: {requested_path}"
            ) from exc
        return resolved

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.workspace_path).as_posix()

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.workspace_path)
        except ValueError:
            return False
        return True

    def list_files(self, path: str = ".", recursive: bool = False) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path}")

        entries = target.rglob("*") if recursive else target.iterdir()
        files = sorted(
            self._relative_path(entry)
            for entry in entries
            if self._is_within_workspace(entry) and entry.is_file()
        )
        return {"path": self._relative_path(target) or ".", "recursive": recursive, "files": files}

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        lines = target.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        actual_end = start_line + len(selected) - 1 if selected else start_line - 1
        return {
            "path": self._relative_path(target),
            "start_line": start_line,
            "end_line": actual_end,
            "content": "\n".join(selected),
        }

    def search_code(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        candidates = [target] if target.is_file() else sorted(target.rglob("*"))
        matches: list[dict[str, Any]] = []

        for candidate in candidates:
            if not self._is_within_workspace(candidate) or not candidate.is_file():
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for index, line in enumerate(lines):
                if query not in line:
                    continue
                context_start = max(0, index - 2)
                context_end = min(len(lines), index + 3)
                matches.append(
                    {
                        "file": self._relative_path(candidate),
                        "line_number": index + 1,
                        "matching_line": line,
                        "small_context": "\n".join(lines[context_start:context_end]),
                    }
                )
                if len(matches) >= max_results:
                    return {"query": query, "path": path, "matches": matches, "truncated": True}

        return {"query": query, "path": path, "matches": matches, "truncated": False}

    def _run_git(self, arguments: list[str], input_text: str | None = None) -> str:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=self.workspace_path,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitOperationError(f"Git command failed to start or timed out: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise GitOperationError(detail or f"Git exited with code {completed.returncode}")
        return completed.stdout

    def _patch_paths(self, patch: str) -> list[str]:
        paths = set()
        for line in patch.splitlines():
            if not (line.startswith("--- ") or line.startswith("+++ ")):
                continue
            raw_path = line[4:].split("\t", 1)[0].strip()
            if raw_path == "/dev/null":
                continue
            if raw_path.startswith(("a/", "b/")):
                raw_path = raw_path[2:]
            self._resolve_path(raw_path)
            paths.add(Path(raw_path).as_posix())
        if not paths:
            raise PatchApplyError("Patch does not contain file headers")
        return sorted(paths)

    def apply_patch(self, patch: str) -> dict[str, Any]:
        affected_paths = self._patch_paths(patch)
        try:
            options = ["--ignore-space-change", "--whitespace=nowarn", "-"]
            self._run_git(["apply", "--check", *options], input_text=patch)
            self._run_git(["apply", *options], input_text=patch)
        except GitOperationError as exc:
            raise PatchApplyError(str(exc)) from exc
        return {"affected_paths": affected_paths, "applied": True}

    def git_diff(self) -> dict[str, Any]:
        changed_files = [
            line for line in self._run_git(["diff", "--name-only", "--"]).splitlines() if line
        ]
        diff = self._run_git(["diff", "--no-ext-diff", "--"])
        diff_stats = self._run_git(["diff", "--stat", "--"])
        truncated = len(diff) > self.max_diff_chars
        return {
            "changed_files": changed_files,
            "diff": diff[: self.max_diff_chars],
            "diff_stats": diff_stats,
            "truncated": truncated,
        }

    @staticmethod
    def _pytest_counts(output: str) -> tuple[int, int]:
        passed = re.search(r"(\d+) passed", output)
        failed = re.search(r"(\d+) failed", output)
        return (int(passed.group(1)) if passed else 0, int(failed.group(1)) if failed else 0)

    def _truncate_output(self, output: str) -> tuple[str, bool]:
        if len(output) <= self.max_output_chars:
            return output, False
        half = max(1, self.max_output_chars // 2)
        return output[:half] + "\n... output truncated ...\n" + output[-half:], True

    def run_tests(
        self,
        test_path: str | None = None,
        test_selector: str | None = None,
    ) -> dict[str, Any]:
        if test_selector and not test_path:
            raise InvalidTestSelectionError("test_selector requires test_path")
        if test_selector and not re.fullmatch(r"[A-Za-z0-9_:.\[\]-]+", test_selector):
            raise InvalidTestSelectionError("test_selector contains unsupported characters")

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ]
        if test_path:
            resolved_test_path = self._resolve_path(test_path)
            if not resolved_test_path.exists():
                raise FileNotFoundError(f"Test path not found: {test_path}")
            node = self._relative_path(resolved_test_path)
            if test_selector:
                node = f"{node}::{test_selector}"
            command.append(node)

        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.test_timeout_seconds,
                env=environment,
                check=False,
            )
            exit_code: int | None = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            timed_out = True

        duration_ms = round((time.perf_counter() - started) * 1000)
        combined = f"{stdout}\n{stderr}"
        passed_count, failed_count = self._pytest_counts(combined)
        stdout, stdout_truncated = self._truncate_output(stdout)
        stderr, stderr_truncated = self._truncate_output(stderr)
        return {
            "command": command,
            "exit_code": exit_code,
            "passed": exit_code == 0 and not timed_out,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "output_truncated": stdout_truncated or stderr_truncated,
        }
