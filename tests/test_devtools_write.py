from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.tools import ToolCall
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider

FIXTURE = Path("fixtures/simple_bug")
PATCH = """\
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def multiply(left: int, right: int) -> int:
-    return left + right
+    return left * right
"""


@pytest.fixture
def bug_workspace() -> Iterator[Path]:
    workspace = Path(".test_runtime") / f"simple_bug_{uuid4().hex}"
    shutil.copytree(FIXTURE, workspace)
    for arguments in (
        ["init", "-q"],
        ["config", "user.email", "tests@evodev.local"],
        ["config", "user.name", "EvoDev Tests"],
        ["add", "."],
        ["commit", "-q", "-m", "fixture baseline"],
    ):
        subprocess.run(["git", *arguments], cwd=workspace, check=True)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, onerror=_remove_readonly)


def _remove_readonly(
    function: Callable[[str], object],
    path: str,
    _error_info: object,
) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _call(provider: NativeToolProvider, name: str, **arguments: object):
    return provider.call_tool(ToolCall(call_id=name, name=name, arguments=arguments))


def test_patch_diff_and_test_cycle(bug_workspace: Path) -> None:
    provider = NativeToolProvider(DevToolsService(bug_workspace))

    failing = _call(provider, "run_tests", test_path="tests/test_calculator.py")
    applied = _call(provider, "apply_patch", patch=PATCH)
    diff = _call(provider, "git_diff")
    passing = _call(provider, "run_tests", test_path="tests/test_calculator.py")

    assert not failing.success and failing.error_type == "TEST_FAILED"
    assert failing.data["failed_count"] == 1
    assert applied.success and applied.data["affected_paths"] == ["src/calculator.py"]
    assert diff.success and diff.data["changed_files"] == ["src/calculator.py"]
    assert "return left * right" in diff.data["diff"]
    assert passing.success and passing.data["passed_count"] == 1


def test_apply_patch_rejects_escape_and_invalid_patch(bug_workspace: Path) -> None:
    provider = NativeToolProvider(DevToolsService(bug_workspace))
    escape_patch = "--- a/../outside.py\n+++ b/../outside.py\n@@ -0,0 +1 @@\n+x\n"

    escaped = _call(provider, "apply_patch", patch=escape_patch)
    invalid = _call(provider, "apply_patch", patch="not a unified patch")

    assert escaped.error_type == "PATH_OUTSIDE_WORKSPACE"
    assert invalid.error_type == "PATCH_APPLY_FAILED"


def test_run_tests_rejects_uncontrolled_selector(bug_workspace: Path) -> None:
    provider = NativeToolProvider(DevToolsService(bug_workspace))

    result = _call(
        provider,
        "run_tests",
        test_path="tests/test_calculator.py",
        test_selector="test_multiply;whoami",
    )

    assert result.error_type == "INVALID_TOOL_ARGUMENTS"


def test_run_tests_normalizes_timeout(bug_workspace: Path) -> None:
    slow_test = bug_workspace / "tests" / "test_slow.py"
    slow_test.write_text(
        "import time\n\ndef test_slow():\n    time.sleep(5)\n",
        encoding="utf-8",
    )
    provider = NativeToolProvider(DevToolsService(bug_workspace, test_timeout_seconds=0.1))

    result = _call(provider, "run_tests", test_path="tests/test_slow.py")

    assert not result.success
    assert result.error_type == "TEST_TIMEOUT"
    assert result.data["timed_out"] is True
