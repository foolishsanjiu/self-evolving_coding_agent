"""Dependency-light policy types used directly by the ReAct runtime."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InspectTestsMode(StrEnum):
    OFF = "off"
    PREFER = "prefer"
    REQUIRE = "require"


class AgentPolicy(BaseModel):
    """The complete v1 evolvable search space: exactly three fields."""

    model_config = ConfigDict(extra="forbid")

    inspect_tests_before_edit: InspectTestsMode = InspectTestsMode.OFF
    prefer_search_before_read: bool = False
    max_react_steps: Literal[10, 15, 20] = 15

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def guidance(self) -> str:
        lines = []
        if self.inspect_tests_before_edit == InspectTestsMode.PREFER:
            lines.append("Prefer inspecting relevant tests before the first edit.")
        elif self.inspect_tests_before_edit == InspectTestsMode.REQUIRE:
            lines.append(
                "Required: inspect relevant tests before apply_patch; the harness enforces this."
            )
        if self.prefer_search_before_read:
            lines.append("Prefer search_code before broad read_file exploration.")
        return "Policy Guidance:\n" + "\n".join(f"- {line}" for line in lines) if lines else ""
