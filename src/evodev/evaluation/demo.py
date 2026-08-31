"""Render a concise CLI demo from persisted public artifacts."""

from __future__ import annotations

from pathlib import Path

from evodev.evaluation.models import EvaluationResult
from evodev.trajectory import TraceAnalyzer


def render_cli_demo(run_path: Path, evaluation_report: Path) -> list[str]:
    run_root = run_path.resolve()
    patch_path = run_root / "final.patch"
    if not patch_path.is_file():
        raise FileNotFoundError("Final Patch artifact is missing")
    evaluation = EvaluationResult.model_validate_json(
        evaluation_report.read_text(encoding="utf-8")
    )
    lines = []
    for event in TraceAnalyzer.load_events(run_root / "events.jsonl"):
        if event.get("type") != "TOOL_CALL":
            continue
        call = event.get("data", {}).get("tool_call", {})
        name = call.get("name")
        arguments = call.get("arguments", {})
        if name == "search_code":
            lines.append(f"[SEARCH] {arguments.get('query', '')}")
        elif name == "read_file":
            lines.append(f"[READ] {arguments.get('path', '')}")
        elif name == "apply_patch":
            lines.append("[PATCH] apply_patch")
        elif name == "run_tests":
            target = arguments.get("test_selector") or arguments.get("test_path") or "all"
            lines.append(f"[TEST] {target}")
    lines.append(f"[FINAL PATCH] {patch_path}")
    lines.append(f"[EVAL] {evaluation.failure_type.value}")
    return lines
