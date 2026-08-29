"""Controlled one-shot Docker execution for pytest."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from evodev.config import SandboxSettings
from evodev.tools.devtools import InvalidTestSelectionError, PathOutsideWorkspaceError


class SandboxUnavailableError(RuntimeError):
    """Raised when Docker or the configured sandbox image cannot run."""


class SandboxCleanupError(RuntimeError):
    """Raised when a disposable test container cannot be proven removed."""


class DockerTestRunner:
    """Run one controlled pytest invocation in one disposable container."""

    def __init__(
        self,
        settings: SandboxSettings,
        artifacts_root: Path,
        docker_executable: str = "docker",
    ) -> None:
        self.settings = settings
        self.artifacts_root = artifacts_root.resolve()
        self.docker_executable = docker_executable

    def verify_available(self) -> str:
        """Return the Docker Server version or raise a normalized availability error."""
        try:
            completed = subprocess.run(
                [self.docker_executable, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailableError(f"Docker is unavailable: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise SandboxUnavailableError(detail or "Docker Server is unavailable")
        return completed.stdout.strip()

    @staticmethod
    def _test_node(
        workspace_path: Path,
        test_path: str | None,
        test_selector: str | None,
    ) -> str | None:
        if test_selector and not test_path:
            raise InvalidTestSelectionError("test_selector requires test_path")
        if test_selector and not re.fullmatch(r"[A-Za-z0-9_:.[\]-]+", test_selector):
            raise InvalidTestSelectionError("test_selector contains unsupported characters")
        if not test_path:
            return None
        requested = Path(test_path)
        candidate = requested if requested.is_absolute() else workspace_path / requested
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(workspace_path)
        except ValueError as exc:
            raise PathOutsideWorkspaceError(f"Path escapes workspace: {test_path}") from exc
        if not resolved.exists():
            raise FileNotFoundError(f"Test path not found: {test_path}")
        node = relative.as_posix()
        return f"{node}::{test_selector}" if test_selector else node

    def build_command(
        self,
        workspace_path: Path,
        container_name: str,
        test_node: str | None,
    ) -> list[str]:
        """Build the fixed Docker and pytest argument vector without a shell."""
        workspace = workspace_path.resolve(strict=True)
        if "," in str(workspace):
            raise ValueError("Workspace path cannot contain a comma for Docker --mount")
        command = [
            self.docker_executable,
            "run",
            "--pull",
            "never",
            "--name",
            container_name,
            "--network",
            self.settings.network,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            self.settings.memory_limit,
            "--cpus",
            str(self.settings.cpus),
            "--pids-limit",
            str(self.settings.pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--workdir",
            "/workspace",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            self.settings.image,
            "python",
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ]
        if test_node:
            command.append(test_node)
        return command

    def _container_exists(self, container_name: str) -> bool:
        try:
            completed = subprocess.run(
                [self.docker_executable, "inspect", container_name],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return completed.returncode == 0

    def _remove_container(self, container_name: str) -> bool:
        try:
            subprocess.run(
                [self.docker_executable, "rm", "--force", container_name],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return not self._container_exists(container_name)

    @staticmethod
    def _observation(path: Path, limit: int) -> tuple[str, bool]:
        with path.open("rb") as stream:
            head = stream.read(limit // 2)
            stream.seek(0, 2)
            size = stream.tell()
            if size <= limit:
                stream.seek(0)
                return stream.read().decode("utf-8", errors="replace"), False
            stream.seek(max(0, size - limit // 2))
            tail = stream.read(limit // 2)
        text = head.decode("utf-8", errors="replace")
        text += "\n... output truncated ...\n"
        text += tail.decode("utf-8", errors="replace")
        return text, True

    @staticmethod
    def _pytest_counts(output: str) -> tuple[int, int]:
        passed = re.search(r"(\d+) passed", output)
        failed = re.search(r"(\d+) failed", output)
        return (int(passed.group(1)) if passed else 0, int(failed.group(1)) if failed else 0)

    def run_tests(
        self,
        workspace_path: Path,
        test_path: str | None = None,
        test_selector: str | None = None,
    ) -> dict[str, Any]:
        """Execute pytest, save full output, and return a bounded observation."""
        workspace = workspace_path.resolve(strict=True)
        if self.artifacts_root.is_relative_to(workspace):
            raise ValueError("Sandbox artifacts must be stored outside the mounted workspace")
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        test_node = self._test_node(workspace, test_path, test_selector)
        invocation_id = f"test_{uuid4().hex}"
        container_name = f"evodev-{invocation_id.replace('_', '-')}"
        artifact_path = self.artifacts_root / invocation_id
        artifact_path.mkdir()
        stdout_path = artifact_path / "stdout.txt"
        stderr_path = artifact_path / "stderr.txt"
        metadata_path = artifact_path / "metadata.json"
        command = self.build_command(workspace, container_name, test_node)
        test_command = ["python", "-m", "pytest", "-q"]
        if test_node:
            test_command.append(test_node)

        started = time.perf_counter()
        timed_out = False
        exit_code: int | None = None
        container_created = False
        container_removed = False
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=workspace,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        text=True,
                    )
                except OSError as exc:
                    raise SandboxUnavailableError(f"Docker is unavailable: {exc}") from exc
                try:
                    exit_code = process.wait(timeout=self.settings.test_timeout_seconds)
                    container_created = self._container_exists(container_name)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    container_created = self._container_exists(container_name)
                    if container_created:
                        container_removed = self._remove_container(container_name)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        finally:
            if container_created and not container_removed:
                container_removed = self._remove_container(container_name)

        duration_ms = round((time.perf_counter() - started) * 1000)
        stream_limit = max(1, self.settings.max_output_chars // 2)
        stdout, stdout_truncated = self._observation(stdout_path, stream_limit)
        stderr, stderr_truncated = self._observation(stderr_path, stream_limit)
        passed_count, failed_count = self._pytest_counts(f"{stdout}\n{stderr}")
        metadata = {
            "container_name": container_name,
            "docker_command": command,
            "test_command": test_command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "container_created": container_created,
            "container_removed": container_removed,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        if not container_created and exit_code != 0:
            raise SandboxUnavailableError(stderr.strip() or "Docker did not create the container")
        if container_created and not container_removed:
            raise SandboxCleanupError(f"Container was not removed: {container_name}")
        return {
            "command": test_command,
            "exit_code": exit_code,
            "passed": exit_code == 0 and not timed_out,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "output_truncated": stdout_truncated or stderr_truncated,
            "container_name": container_name,
            "container_removed": container_removed,
            "artifact_path": str(artifact_path),
        }
