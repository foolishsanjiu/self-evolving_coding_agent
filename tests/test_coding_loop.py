from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.agent import AgentStatus, ReActAgent
from evodev.llm import FakeLLM, ModelTurn
from evodev.sandbox import WorkspaceManager
from evodev.schemas import TaskSpec
from evodev.tools import MCPToolProvider, ToolCall
from mcp_servers.devtools.server import build_server

FIXTURE = Path("fixtures/simple_bug")
CORRECT_PATCH = """\
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def multiply(left: int, right: int) -> int:
-    return left + right
+    return left * right
"""
WRONG_PATCH = CORRECT_PATCH.replace("return left * right", "return left - right")
REPAIR_PATCH = CORRECT_PATCH.replace("return left + right", "return left - right")


def _remove_readonly(
    function: Callable[[str], object],
    path: str,
    _error_info: object,
) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


@pytest.fixture
def runs_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"coding_loop_{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, onerror=_remove_readonly)


class ScriptedTestRunner:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = list(results)
        self.calls = 0

    def run_tests(self, workspace_path, test_path=None, test_selector=None):
        self.calls += 1
        return self.results.pop(0)


def _test_result(*, passed: bool, timed_out: bool = False) -> dict[str, object]:
    return {
        "command": ["python", "-m", "pytest", "-q"],
        "exit_code": None if timed_out else (0 if passed else 1),
        "passed": passed,
        "passed_count": 1 if passed else 0,
        "failed_count": 0 if passed else 1,
        "stdout": "1 passed" if passed else "1 failed",
        "stderr": "",
        "duration_ms": 1,
        "timed_out": timed_out,
        "output_truncated": False,
        "container_removed": True,
    }


def _turn(call_id: str, name: str, **arguments: object) -> ModelTurn:
    return ModelTurn(
        tool_calls=[ToolCall(call_id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def _run_agent(
    runs_root: Path,
    turns: list[ModelTurn],
    test_results: list[dict[str, object]],
):
    manager = WorkspaceManager(runs_root)
    run = manager.create(FIXTURE)
    runner = ScriptedTestRunner(test_results)
    server = build_server(run.workspace_path, test_runner=runner)
    task = TaskSpec(
        task_id=run.run_id,
        instruction="Fix multiply and verify the tests.",
        workspace_path=run.workspace_path,
    )
    with MCPToolProvider(server) as provider:
        result = ReActAgent(FakeLLM([*turns, ModelTurn(content="done")]), provider).run(task)
    return manager, run, runner, result


def test_demo_a_simple_bug_search_read_patch_test_pass(runs_root: Path) -> None:
    original = (FIXTURE / "src/calculator.py").read_text(encoding="utf-8")
    manager, run, runner, result = _run_agent(
        runs_root,
        [
            _turn("search", "search_code", query="return left + right", path="src"),
            _turn("read", "read_file", path="src/calculator.py"),
            _turn("patch", "apply_patch", patch=CORRECT_PATCH),
            _turn("test", "run_tests", test_path="tests/test_calculator.py"),
            _turn("diff", "git_diff"),
        ],
        [_test_result(passed=True)],
    )
    manager.cleanup(run)

    assert result.status == AgentStatus.SUCCESS
    assert runner.calls == 1
    assert result.tool_results[3].success is True
    assert "return left * right" in result.tool_results[4].data["diff"]
    assert "return left * right" in (run.run_path / "final.diff").read_text(
        encoding="utf-8"
    )
    assert (FIXTURE / "src/calculator.py").read_text(encoding="utf-8") == original


def test_demo_b_patch_failure_is_observed_then_corrected(runs_root: Path) -> None:
    manager, run, _, result = _run_agent(
        runs_root,
        [
            _turn("bad-patch", "apply_patch", patch="not a unified patch"),
            _turn("good-patch", "apply_patch", patch=CORRECT_PATCH),
            _turn("test", "run_tests"),
            _turn("diff", "git_diff"),
        ],
        [_test_result(passed=True)],
    )
    manager.cleanup(run)

    assert result.tool_results[0].error_type == "PATCH_APPLY_FAILED"
    assert result.tool_results[1].success is True
    assert result.tool_results[2].success is True


def test_demo_c_failed_change_is_repaired_after_test_observation(runs_root: Path) -> None:
    manager, run, runner, result = _run_agent(
        runs_root,
        [
            _turn("wrong", "apply_patch", patch=WRONG_PATCH),
            _turn("failed-test", "run_tests"),
            _turn("repair", "apply_patch", patch=REPAIR_PATCH),
            _turn("passed-test", "run_tests"),
            _turn("diff", "git_diff"),
        ],
        [_test_result(passed=False), _test_result(passed=True)],
    )
    manager.cleanup(run)

    assert runner.calls == 2
    assert result.tool_results[1].error_type == "TEST_FAILED"
    assert result.tool_results[3].success is True
    assert "return left * right" in result.tool_results[4].data["diff"]


def test_demo_d_infinite_test_timeout_is_observed_after_cleanup(runs_root: Path) -> None:
    manager, run, _, result = _run_agent(
        runs_root,
        [_turn("timeout", "run_tests", test_path="tests/test_calculator.py")],
        [_test_result(passed=False, timed_out=True)],
    )
    manager.cleanup(run)

    timeout = result.tool_results[0]
    assert result.status == AgentStatus.SUCCESS
    assert timeout.error_type == "TEST_TIMEOUT"
    assert timeout.data["container_removed"] is True
