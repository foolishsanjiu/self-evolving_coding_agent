"""Compress public run evidence into a bounded ReflectionContext."""

from __future__ import annotations

import re
from pathlib import Path

from evodev.benchmark import BenchmarkTask
from evodev.evaluation import EvaluationResult
from evodev.experience.models import ReflectionContext
from evodev.trajectory import TraceAnalyzer


def _patch_summary(patch: str) -> str:
    files = re.findall(r"^\+\+\+ b/(.+)$", patch, flags=re.MULTILINE)
    additions = sum(
        line.startswith("+") and not line.startswith("+++") for line in patch.splitlines()
    )
    deletions = sum(
        line.startswith("-") and not line.startswith("---") for line in patch.splitlines()
    )
    return f"files={files or ['none']}; additions={additions}; deletions={deletions}"


class ReflectionContextBuilder:
    def __init__(self, max_events: int = 12, max_failure_chars: int = 2_000) -> None:
        self.max_events = max_events
        self.max_failure_chars = max_failure_chars

    def build(
        self,
        task: BenchmarkTask,
        result: EvaluationResult,
        run_path: Path,
        evaluation_path: Path,
    ) -> ReflectionContext:
        events = TraceAnalyzer.load_events(run_path / "events.jsonl")
        features = TraceAnalyzer.analyze(events)
        selected = [
            event
            for event in events
            if event.get("type") in {"TOOL_CALL", "TOOL_RESULT", "RUN_ERROR", "RUN_FINISHED"}
        ][-self.max_events :]
        important = [
            {
                "seq": event.get("seq"),
                "type": event.get("type"),
                "tool": event.get("data", {}).get("tool_call", {}).get("name")
                or event.get("data", {}).get("result", {}).get("tool_name"),
                "success": event.get("data", {}).get("result", {}).get("success"),
                "error_type": event.get("data", {}).get("result", {}).get("error_type"),
            }
            for event in selected
        ]
        test_output = (evaluation_path / "test_output.txt").read_text(
            encoding="utf-8", errors="replace"
        )
        patch = (run_path / "final.patch").read_text(encoding="utf-8", errors="replace")
        references = [f"event:{item['seq']}" for item in important]
        references.extend(f"feature:{name}" for name in features)
        references.append("evaluator:failure_type")
        return ReflectionContext(
            task_id=task.config.task_id,
            run_id=result.agent_run_id,
            task_description=task.config.description,
            task_type=task.config.category,
            evaluation_failure=result.failure_type,
            final_patch_summary=_patch_summary(patch),
            relevant_test_failure=test_output[-self.max_failure_chars :],
            behavioral_features=features,
            important_events=important,
            allowed_evidence_references=references,
        )
