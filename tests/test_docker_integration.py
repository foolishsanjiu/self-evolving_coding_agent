from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.config import SandboxSettings
from evodev.sandbox import DockerTestRunner, WorkspaceManager
from evodev.tools import MCPToolProvider, ToolCall
from mcp_servers.devtools.server import build_server

IMAGE = "evodev-python:3.11"
PATCH = """\
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def multiply(left: int, right: int) -> int:
-    return left + right
+    return left * right
"""


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    for command in (
        ["docker", "info"],
        ["docker", "image", "inspect", IMAGE],
    ):
        try:
            completed = subprocess.run(command, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if completed.returncode != 0:
            return False
    return True


pytestmark = pytest.mark.skipif(
    not _docker_ready(),
    reason="Docker Server and evodev-python:3.11 image are required",
)


def _remove_readonly(
    function: Callable[[str], object],
    path: str,
    _error_info: object,
) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


@pytest.fixture
def runs_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"docker_integration_{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, onerror=_remove_readonly)


def _sandbox(run, timeout: float = 15) -> DockerTestRunner:
    settings = SandboxSettings(test_timeout_seconds=timeout)
    return DockerTestRunner(settings, run.artifacts_path)


def test_real_docker_patch_test_cycle(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    run = manager.create(Path("fixtures/simple_bug"))
    server = build_server(run.workspace_path, test_runner=_sandbox(run))
    with MCPToolProvider(server) as provider:
        failing = provider.call_tool(
            ToolCall(call_id="fail", name="run_tests", arguments={"test_path": "tests"})
        )
        applied = provider.call_tool(
            ToolCall(call_id="patch", name="apply_patch", arguments={"patch": PATCH})
        )
        passing = provider.call_tool(
            ToolCall(call_id="pass", name="run_tests", arguments={"test_path": "tests"})
        )
    manager.cleanup(run)

    assert failing.error_type == "TEST_FAILED"
    assert applied.success
    assert passing.success
    assert failing.data["container_removed"] and passing.data["container_removed"]
    assert "return left * right" in (run.artifacts_path / "final.diff").read_text(
        encoding="utf-8"
    )


def test_real_docker_isolation_probe(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    run = manager.create(Path("fixtures/sandbox_probe"))

    result = _sandbox(run).run_tests(run.workspace_path, "tests")
    manager.cleanup(run)

    assert result["passed"]
    assert result["container_removed"]


def test_real_docker_timeout_force_removes_container(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    run = manager.create(Path("fixtures/infinite_test"))

    result = _sandbox(run, timeout=2).run_tests(run.workspace_path, "tests")
    inspected = subprocess.run(
        ["docker", "inspect", result["container_name"]],
        capture_output=True,
        timeout=15,
        check=False,
    )
    manager.cleanup(run)

    assert result["timed_out"]
    assert result["container_removed"]
    assert inspected.returncode != 0
