"""Deterministic model used by harness unit tests and development fixtures."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from evodev.llm.schemas import ModelTurn
from evodev.tools import ToolSpec


class FakeLLM:
    """Return queued model turns or raise queued exceptions."""

    def __init__(self, responses: list[ModelTurn | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[list[dict[str, Any]], list[ToolSpec]]] = []

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
    ) -> ModelTurn:
        self.requests.append((deepcopy(messages), list(tools or [])))
        if not self.responses:
            raise RuntimeError("FakeLLM has no queued response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
