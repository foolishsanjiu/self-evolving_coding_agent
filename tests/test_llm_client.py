from types import SimpleNamespace

from evodev.config import ModelSettings
from evodev.llm import LLMClient
from evodev.tools import ToolSpec


class FakeCompletions:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="read_file", arguments='{"path":"README.md"}'),
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=[tool_call]),
                    finish_reason="tool_calls",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7),
        )


def test_generate_normalizes_provider_response() -> None:
    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = ModelSettings(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="UNUSED_IN_FAKE",
    )

    turn = LLMClient(settings, client=fake_client).generate(
        [{"role": "user", "content": "Inspect the repository"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert turn.finish_reason == "tool_calls"
    assert turn.input_tokens == 12
    assert turn.output_tokens == 7
    assert turn.tool_calls[0].call_id == "call-1"
    assert turn.tool_calls[0].arguments == {"path": "README.md"}
    assert completions.request["model"] == "deepseek-chat"


def test_generate_adapts_canonical_messages_and_tools() -> None:
    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = ModelSettings(
        provider="deepseek",
        model="deepseek-chat",
        api_key_env="UNUSED_IN_FAKE",
    )
    tool = ToolSpec(
        name="read_file",
        description="Read a file.",
        input_schema={"type": "object"},
        source="native",
        read_only=True,
        destructive=False,
        idempotent=True,
    )

    LLMClient(settings, client=fake_client).generate(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"call_id": "call-0", "name": "read_file", "arguments": {"path": "a.py"}}
                ],
            }
        ],
        tools=[tool],
    )

    request = completions.request
    assert request["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert request["messages"][0]["tool_calls"][0]["id"] == "call-0"
