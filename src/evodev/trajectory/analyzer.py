"""Five stable behavioral features derived from public trajectory events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TraceAnalyzer:
    """Compute the minimal v1.0 trace feature schema."""

    @staticmethod
    def load_events(events_path: Path) -> list[dict[str, Any]]:
        events = []
        if not events_path.is_file():
            return events
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    @staticmethod
    def analyze(events: list[dict[str, Any]]) -> dict[str, bool | int]:
        calls = [
            event["data"]["tool_call"]
            for event in events
            if event.get("type") == "TOOL_CALL" and "tool_call" in event.get("data", {})
        ]
        first_edit = next(
            (index for index, call in enumerate(calls) if call.get("name") == "apply_patch"),
            len(calls),
        )
        before_edit = calls[:first_edit]
        files_read = {
            str(call.get("arguments", {}).get("path"))
            for call in calls
            if call.get("name") == "read_file" and call.get("arguments", {}).get("path")
        }

        def inspects_tests(call: dict[str, Any]) -> bool:
            if call.get("name") not in {"read_file", "search_code"}:
                return False
            path = str(call.get("arguments", {}).get("path", "")).replace("\\", "/").lower()
            return path == "tests" or path.startswith("tests/") or "/tests/" in f"/{path}/"

        return {
            "searched_before_edit": any(
                call.get("name") == "search_code" for call in before_edit
            ),
            "inspected_tests_before_edit": any(inspects_tests(call) for call in before_edit),
            "unique_files_read": len(files_read),
            "patch_attempts": sum(call.get("name") == "apply_patch" for call in calls),
            "test_runs": sum(call.get("name") == "run_tests" for call in calls),
        }

    def analyze_file(self, events_path: Path) -> dict[str, bool | int]:
        return self.analyze(self.load_events(events_path))
