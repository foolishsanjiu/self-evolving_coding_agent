from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.agent import AgentStatus, ReActAgent
from evodev.agent.events import AgentEvent
from evodev.llm import FakeLLM
from evodev.sandbox import WorkspaceManager
from evodev.schemas import TaskSpec
from evodev.tools import ToolSpec
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider
from evodev.trajectory import (
    REDACTED,
    RunMetadata,
    TraceAnalyzer,
    TrajectoryRecorder,
    tool_catalog_hash,
)


@pytest.fixture
def trajectory_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"trajectory_{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _metadata(run_id: str = "run_trajectory", task_id: str = "task-7") -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        task_id=task_id,
        agent_release="0.2.0",
        policy_version="none",
        policy_hash="none",
        experience_version="none",
        experience_hash="none",
        model="fake-model",
        temperature=0.1,
        prompt_version="react-v1",
        max_steps=15,
        context_budget=60_000,
        tool_provider="native",
        tool_catalog_hash="catalog-hash",
        benchmark_version="development",
        benchmark_hash="none",
        sandbox_image="evodev-python:3.11",
        sandbox_digest="sha256:test",
    )


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tool_call(call_id: str, name: str, **arguments: object) -> AgentEvent:
    return AgentEvent(
        type="TOOL_CALL",
        data={
            "tool_call": {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            }
        },
    )


def test_records_ordered_events_and_correlates_tool_call_result(
    trajectory_root: Path,
) -> None:
    recorder = TrajectoryRecorder(trajectory_root / "run", _metadata())
    recorder.emit(AgentEvent(type="RUN_STARTED", data={"task_id": "task-7"}))
    recorder.emit(_tool_call("read-1", "read_file", path="src/app.py"))
    recorder.emit(
        AgentEvent(
            type="TOOL_RESULT",
            data={
                "result": {
                    "call_id": "read-1",
                    "tool_name": "read_file",
                    "success": True,
                    "content": "ok",
                    "data": {"path": "src/app.py"},
                    "error_type": None,
                    "duration_ms": 1,
                }
            },
        )
    )
    recorder.emit(AgentEvent(type="RUN_FINISHED", data={"status": "SUCCESS"}))

    events = _events(recorder.events_path)
    metadata = json.loads(recorder.run_json_path.read_text(encoding="utf-8"))

    assert [event["seq"] for event in events] == [1, 2, 3, 4]
    assert events[1]["data"]["tool_call"]["call_id"] == "read-1"
    assert events[2]["data"]["result"]["call_id"] == "read-1"
    assert metadata["trajectory_format_version"] == "1.0"
    assert metadata["status"] == "SUCCESS"
    assert metadata["finished_at"] is not None
    assert recorder.trace_features_path.is_file()


def test_large_outputs_use_integrity_checked_redacted_artifacts(
    trajectory_root: Path,
) -> None:
    run_path = trajectory_root / "run"
    docker_artifact = run_path / "artifacts/test_external"
    docker_artifact.mkdir(parents=True)
    env_file = trajectory_root / ".env"
    env_file.write_text("PRIVATE_VALUE=env-secret-value\n", encoding="utf-8")
    secret = "known-secret-value"
    stdout = (
        "x" * 100
        + secret
        + " env-secret-value Authorization: Bearer bearer-secret "
        + "sk-abcdefghijklmnop"
    )
    (docker_artifact / "stdout.txt").write_text(stdout, encoding="utf-8")
    (docker_artifact / "stderr.txt").write_text("", encoding="utf-8")
    tool_data = {
        "stdout": "preview",
        "stderr": "",
        "artifact_path": str(docker_artifact),
        "output_truncated": True,
    }
    recorder = TrajectoryRecorder(
        run_path,
        _metadata(),
        known_secrets=[secret],
        env_file=env_file,
        max_inline_chars=40,
    )

    recorder.emit(_tool_call("patch-1", "apply_patch", patch="+" + "z" * 100))
    recorder.emit(
        AgentEvent(
            type="TOOL_RESULT",
            data={
                "result": {
                    "call_id": "test-1",
                    "tool_name": "run_tests",
                    "success": True,
                    "content": json.dumps(tool_data),
                    "data": tool_data,
                    "error_type": None,
                    "duration_ms": 1,
                }
            },
        )
    )

    events = _events(recorder.events_path)
    patch_ref = events[0]["data"]["tool_call"]["arguments"]["patch"]
    stdout_ref = events[1]["data"]["result"]["data"]["stdout"]
    persisted_files = [path for path in run_path.rglob("*") if path.is_file()]
    persisted_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in persisted_files
    )

    assert set(patch_ref) == {"artifact_ref", "sha256", "chars", "truncated_for_llm"}
    assert stdout_ref["truncated_for_llm"] is True
    assert len(stdout_ref["sha256"]) == 64
    stdout_artifact = run_path / stdout_ref["artifact_ref"]
    stdout_text = stdout_artifact.read_text(encoding="utf-8")
    assert stdout_ref["chars"] == len(stdout_text)
    assert stdout_ref["sha256"] == hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
    assert events[1]["data"]["result"]["content"] == "[structured result stored in data]"
    assert secret not in persisted_text
    assert "env-secret-value" not in persisted_text
    assert "bearer-secret" not in persisted_text
    assert "sk-abcdefghijklmnop" not in persisted_text
    assert REDACTED in persisted_text


def test_trace_analyzer_outputs_exactly_five_core_features(trajectory_root: Path) -> None:
    recorder = TrajectoryRecorder(trajectory_root / "run", _metadata())
    for event in (
        _tool_call("search", "search_code", query="multiply", path="src"),
        _tool_call("tests", "read_file", path="tests/test_calculator.py"),
        _tool_call("source", "read_file", path="src/calculator.py"),
        _tool_call("patch-1", "apply_patch", patch="first"),
        _tool_call("test-1", "run_tests"),
        _tool_call("patch-2", "apply_patch", patch="second"),
        _tool_call("test-2", "run_tests"),
    ):
        recorder.emit(event)
    recorder.emit(AgentEvent(type="RUN_FINISHED", data={"status": "SUCCESS"}))

    features = TraceAnalyzer().analyze_file(recorder.events_path)

    assert features == {
        "searched_before_edit": True,
        "inspected_tests_before_edit": True,
        "unique_files_read": 2,
        "patch_attempts": 2,
        "test_runs": 2,
    }
    assert set(features) == {
        "searched_before_edit",
        "inspected_tests_before_edit",
        "unique_files_read",
        "patch_attempts",
        "test_runs",
    }


def test_recorder_truncates_partial_tail_and_resumes_sequence(trajectory_root: Path) -> None:
    run_path = trajectory_root / "run"
    metadata = _metadata()
    first = TrajectoryRecorder(run_path, metadata)
    first.emit(AgentEvent(type="RUN_STARTED", data={}))
    with first.events_path.open("ab") as stream:
        stream.write(b'{"seq":2,"type":"MODEL_TURN"')

    resumed = TrajectoryRecorder(run_path, metadata)
    resumed.emit(AgentEvent(type="MODEL_TURN", data={"step_count": 1}))

    events = _events(resumed.events_path)
    assert [event["seq"] for event in events] == [1, 2]


def test_agent_error_keeps_flushed_events_without_private_reasoning(
    trajectory_root: Path,
) -> None:
    fixture = Path("fixtures/simple_read")
    provider = NativeToolProvider(DevToolsService(fixture))
    recorder = TrajectoryRecorder(trajectory_root / "run", _metadata(task_id="crash-task"))
    task = TaskSpec(
        task_id="crash-task",
        instruction="Trigger a model failure.",
        workspace_path=fixture,
    )

    agent = ReActAgent(
        FakeLLM([RuntimeError("model crashed")]),
        provider,
        event_sink=recorder,
    )
    result = agent.run(task)

    events = _events(recorder.events_path)
    assert result.status == AgentStatus.ERROR
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR", "RUN_FINISHED"]
    assert all("chain_of_thought" not in json.dumps(event) for event in events)


def test_workspace_final_patch_and_diff_are_redacted_before_persistence(
    trajectory_root: Path,
) -> None:
    manager = WorkspaceManager(trajectory_root)
    run = manager.create(Path("fixtures/simple_bug"), run_id="run_redacted_diff")
    secret = "final-diff-secret"
    recorder = TrajectoryRecorder(
        run.run_path,
        _metadata(run_id=run.run_id),
        known_secrets=[secret],
    )
    calculator = run.workspace_path / "src/calculator.py"
    calculator.write_text(
        calculator.read_text(encoding="utf-8") + f"\n# {secret}\n",
        encoding="utf-8",
    )

    manager.cleanup(run, redact=recorder.redactor.redact_text)

    final_patch = (run.run_path / "final.patch").read_text(encoding="utf-8")
    final_diff = (run.run_path / "final.diff").read_text(encoding="utf-8")
    assert secret not in final_patch + final_diff
    assert REDACTED in final_patch and final_patch == final_diff


def test_tool_catalog_hash_is_stable_across_order() -> None:
    first = ToolSpec(
        name="a",
        description="A",
        input_schema={"type": "object"},
        source="test",
        read_only=True,
        destructive=False,
        idempotent=True,
    )
    second = first.model_copy(update={"name": "b", "description": "B"})

    assert tool_catalog_hash([first, second]) == tool_catalog_hash([second, first])


def test_persisted_event_vocabulary_rejects_unknown_events(trajectory_root: Path) -> None:
    recorder = TrajectoryRecorder(trajectory_root / "run", _metadata())

    recorder.emit(AgentEvent(type="TOOL_RETRY", data={"retry_number": 1}))
    with pytest.raises(ValueError, match="Unsupported"):
        recorder.emit(AgentEvent(type="PRIVATE_REASONING", data={"content": "hidden"}))

    assert recorder.events_path.read_text(encoding="utf-8") == ""
