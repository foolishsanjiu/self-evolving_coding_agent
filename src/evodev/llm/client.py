"""Provider-neutral LLM client backed by an OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI

from evodev.config import ModelSettings
from evodev.llm.schemas import ModelTurn
from evodev.tools.contracts import ToolCall

logger = logging.getLogger(__name__)

_TOOL_ARGUMENT_RETRY_LIMIT = 1


class _MalformedToolArguments(ValueError):
    """A provider returned tool arguments that are not a JSON object."""


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
        tools: list[Any] | None = None,
    ) -> ModelTurn:
        """Generate one model turn and record latency and token usage."""
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": self._format_messages(messages),
            "temperature": self.settings.temperature,
        }
        if tools:
            request["tools"] = self._format_tools(tools)

        total_input_tokens = 0
        total_output_tokens = 0
        total_duration_ms = 0
        max_attempts = _TOOL_ARGUMENT_RETRY_LIMIT + 1
        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            response = self._get_client().chat.completions.create(**request)
            total_duration_ms += round((time.perf_counter() - started) * 1000)
            usage = response.usage
            total_input_tokens += usage.prompt_tokens if usage else 0
            total_output_tokens += usage.completion_tokens if usage else 0

            choice = response.choices[0]
            message = choice.message
            try:
                normalized_calls = self._normalize_tool_calls(message)
            except _MalformedToolArguments as exc:
                logger.warning(
                    "malformed_tool_arguments provider=%s model=%s attempt=%d max_attempts=%d",
                    self.settings.provider,
                    self.settings.model,
                    attempt,
                    max_attempts,
                )
                if attempt == max_attempts:
                    raise ValueError(
                        f"Model tool-call arguments remained invalid after {max_attempts} attempts"
                    ) from exc
                continue

            turn = ModelTurn(
                content=message.content,
                tool_calls=normalized_calls,
                finish_reason=choice.finish_reason,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )
            logger.info(
                "model_call provider=%s model=%s duration_ms=%d input_tokens=%d output_tokens=%d",
                self.settings.provider,
                self.settings.model,
                total_duration_ms,
                turn.input_tokens,
                turn.output_tokens,
            )
            return turn

        raise AssertionError("Model generation retry loop terminated unexpectedly")

    @staticmethod
    def _normalize_tool_calls(message: Any) -> list[ToolCall]:
        normalized_calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError as exc:
                raise _MalformedToolArguments(
                    "Model tool-call arguments are not valid JSON"
                ) from exc
            if not isinstance(arguments, dict):
                raise _MalformedToolArguments(
                    "Model tool-call arguments must decode to an object"
                )
            normalized_calls.append(
                ToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )
        return normalized_calls

    @staticmethod
    def _format_tools(tools: list[Any]) -> list[dict[str, Any]]:
        formatted = []
        for tool in tools:
            data = tool.model_dump() if hasattr(tool, "model_dump") else tool
            if data.get("type") == "function":
                formatted.append(data)
                continue
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": data["name"],
                        "description": data["description"],
                        "parameters": data["input_schema"],
                    },
                }
            )
        return formatted

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted = []
        for message in messages:
            if message["role"] != "assistant" or not message.get("tool_calls"):
                formatted.append(message)
                continue
            calls = []
            for call in message["tool_calls"]:
                data = call.model_dump() if hasattr(call, "model_dump") else call
                calls.append(
                    {
                        "id": data["call_id"],
                        "type": "function",
                        "function": {
                            "name": data["name"],
                            "arguments": json.dumps(data["arguments"]),
                        },
                    }
                )
            formatted.append(
                {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
            )
        return formatted
