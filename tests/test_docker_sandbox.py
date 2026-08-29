from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.config import SandboxSettings
from evodev.sandbox import DockerTestRunner, SandboxCleanupError, SandboxUnavailableError
from evodev.tools import ToolCall
from evodev.tools.devtools import (
    DevToolsService,
    InvalidTestSelectionError,
    PathOutsideWorkspaceError,
)
from evodev.tools.native import NativeToolProvider

FIXTURE = Path("fixtures/simple_bug").resolve()


class FakeDocker:
    def __init__(self, exit_code: int = 0, stdout: str = "1 passed\n", stderr: str = ""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.container_exists = False
        self.removed_names: list[str] = []
        self.timeout = False

    def popen(self, command, *, cwd, stdout, stderr, text):
        self.container_exists = True
        stdout.write(self.stdout)
        stderr.write(self.stderr)
        return FakeProcess(command, self)

    def run(self, command, **kwargs):
        if command[1] == "version":
            return subprocess.CompletedProcess(command, 0, "27.0.0\n", "")
        if command[1] == "inspect":
            return subprocess.CompletedProcess(command, 0 if self.container_exists else 1)
        if command[1] == "rm":
            self.removed_names.append(command[-1])
            self.container_exists = False
            return subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"Unexpected Docker command: {command}")


class FakeProcess:
    def __init__(self, command: list[str], docker: FakeDocker) -> None:
        self.command = command
        self.docker = docker
        self.wait_calls = 0
        self.killed = False

    def wait(self, timeout: float) -> int:
        self.wait_calls += 1
        if self.docker.timeout and self.wait_calls == 1:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.docker.exit_code

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def artifacts_root() -> Path:
    path = Path(".test_runtime") / f"docker_artifacts_{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def _runner(artifacts_root: Path, **settings) -> DockerTestRunner:
    return DockerTestRunner(SandboxSettings(**settings), artifacts_root)


def test_build_command_enforces_mount_and_resource_boundaries(artifacts_root: Path) -> None:
    runner = _runner(artifacts_root)

    command = runner.build_command(FIXTURE, "evodev-test", "tests/test_calculator.py")

    assert command.count("--mount") == 1
    assert f"type=bind,source={FIXTURE},target=/workspace" in command
    for required in (
        "--network",
        "none",
        "--pull",
        "never",
        "--cap-drop",
        "ALL",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--pids-limit",
        "128",
        "--read-only",
        "no-new-privileges:true",
    ):
        assert required in command
    assert "--privileged" not in command
    assert not any("docker.sock" in argument for argument in command)
    assert command[-1] == "tests/test_calculator.py"


def test_run_tests_saves_full_output_and_returns_bounded_observation(
    artifacts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDocker(stdout="x" * 300 + "\n1 passed\n")
    monkeypatch.setattr(subprocess, "Popen", fake.popen)
    monkeypatch.setattr(subprocess, "run", fake.run)
    runner = _runner(artifacts_root, max_output_chars=100)

    result = runner.run_tests(FIXTURE, "tests/test_calculator.py")

    assert result["passed"] is True
    assert result["passed_count"] == 1
    assert result["output_truncated"] is True
    assert result["container_removed"] is True
    assert "output truncated" in result["stdout"]
    artifact = Path(result["artifact_path"])
    assert len((artifact / "stdout.txt").read_text(encoding="utf-8")) > 300
    assert (artifact / "metadata.json").is_file()


def test_test_failure_is_observed_and_container_removed(
    artifacts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDocker(exit_code=1, stdout="1 failed\n")
    monkeypatch.setattr(subprocess, "Popen", fake.popen)
    monkeypatch.setattr(subprocess, "run", fake.run)

    result = _runner(artifacts_root).run_tests(FIXTURE)

    assert result["passed"] is False
    assert result["failed_count"] == 1
    assert result["container_removed"] is True


def test_timeout_force_removes_container(
    artifacts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDocker(exit_code=137)
    fake.timeout = True
    monkeypatch.setattr(subprocess, "Popen", fake.popen)
    monkeypatch.setattr(subprocess, "run", fake.run)

    result = _runner(artifacts_root, test_timeout_seconds=0.01).run_tests(FIXTURE)

    assert result["timed_out"] is True
    assert result["container_removed"] is True
    assert fake.removed_names == [result["container_name"]]


def test_verify_available_normalizes_missing_docker(
    artifacts_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(SandboxUnavailableError, match="unavailable"):
        _runner(artifacts_root).verify_available()


def test_test_selection_cannot_escape_or_inject_arguments(artifacts_root: Path) -> None:
    runner = _runner(artifacts_root)

    with pytest.raises(PathOutsideWorkspaceError):
        runner.run_tests(FIXTURE, "../outside.py")
    with pytest.raises(InvalidTestSelectionError):
        runner.run_tests(
            FIXTURE,
            "tests/test_calculator.py",
            "test_multiply;curl example.test",
        )


def test_artifacts_cannot_be_written_inside_mounted_workspace() -> None:
    runner = DockerTestRunner(SandboxSettings(), FIXTURE / "artifacts")
    try:
        with pytest.raises(ValueError, match="outside"):
            runner.run_tests(FIXTURE, "tests/test_calculator.py")
    finally:
        if (FIXTURE / "artifacts").exists():
            shutil.rmtree(FIXTURE / "artifacts")


def test_devtools_delegates_test_execution_to_injected_runner() -> None:
    class StubRunner:
        def run_tests(self, workspace_path, test_path=None, test_selector=None):
            return {
                "workspace": str(workspace_path),
                "test_path": test_path,
                "test_selector": test_selector,
                "exit_code": 0,
                "timed_out": False,
            }

    service = DevToolsService(FIXTURE, test_runner=StubRunner())

    result = service.run_tests("tests/test_calculator.py", "test_multiply")

    assert result["workspace"] == str(FIXTURE)
    assert result["test_path"] == "tests/test_calculator.py"
    assert result["test_selector"] == "test_multiply"


@pytest.mark.parametrize(
    ("exception", "error_type"),
    [
        (SandboxUnavailableError("missing Docker"), "SANDBOX_UNAVAILABLE"),
        (SandboxCleanupError("container remains"), "SANDBOX_CLEANUP_FAILED"),
    ],
)
def test_native_provider_normalizes_sandbox_failures(
    exception: Exception,
    error_type: str,
) -> None:
    class FailingRunner:
        def run_tests(self, workspace_path, test_path=None, test_selector=None):
            raise exception

    provider = NativeToolProvider(DevToolsService(FIXTURE, test_runner=FailingRunner()))

    result = provider.call_tool(ToolCall(call_id="sandbox", name="run_tests", arguments={}))

    assert result.success is False
    assert result.error_type == error_type
