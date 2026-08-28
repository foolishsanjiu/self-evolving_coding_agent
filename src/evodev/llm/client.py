"""Provider-neutral LLM client backed by an OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI

from evodev.config import ModelSettings
from evodev.llm.schemas import ModelToolCall, ModelTurn

logger = logging.getLogger(__name__)


class LLMClient:
    """Normalize an OpenAI-compatible chat completion into ``ModelTurn``."""

    def __init__(self, settings: ModelSettings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.resolve_api_key(),
                base_url=self.settings.base_url,
            )
        return self._client

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        """Generate one model turn and record latency and token usage."""
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        if tools:
            request["tools"] = tools

        started = time.perf_counter()
        response = self._get_client().chat.completions.create(**request)
        duration_ms = round((time.perf_counter() - started) * 1000)

        choice = response.choices[0]
        message = choice.message
        normalized_calls = []
        for call in message.tool_calls or []:
            arguments = json.loads(call.function.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Model tool-call arguments must decode to an object")
            normalized_calls.append(
                ModelToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        usage = response.usage
        turn = ModelTurn(
            content=message.content,
            tool_calls=normalized_calls,
            finish_reason=choice.finish_reason,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        logger.info(
            "model_call provider=%s model=%s duration_ms=%d input_tokens=%d output_tokens=%d",
            self.settings.provider,
            self.settings.model,
            duration_ms,
            turn.input_tokens,
            turn.output_tokens,
        )
        return turn
