from pathlib import Path

import pytest
from pydantic import ValidationError

from evodev.config import (
    ModelSettings,
    SandboxSettings,
    load_sandbox_settings,
    load_settings,
)


def test_load_settings_and_resolve_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "secret-value")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")

    settings = load_settings(Path("configs"))

    assert settings.model.model == "test-model"
    assert settings.model.base_url == "https://example.test/v1"
    assert settings.agent.max_steps == 15
    assert settings.experience.enabled is True
    assert settings.experience.top_k == 3
    assert settings.experience.max_chars == 2_500
    assert settings.sandbox.network == "none"
    assert settings.sandbox.pids_limit == 128
    assert settings.model.resolve_api_key() == "secret-value"
    assert "secret-value" not in settings.model.model_dump_json()


def test_invalid_model_config_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSettings(
            provider="deepseek",
            model="deepseek-chat",
            temperature=3,
            api_key_env="LLM_API_KEY",
        )


def test_missing_api_key_has_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_settings(Path("configs")).model.resolve_api_key()


def test_sandbox_cannot_disable_required_isolation() -> None:
    with pytest.raises(ValidationError):
        SandboxSettings(network="bridge")
    with pytest.raises(ValidationError):
        SandboxSettings(read_only_rootfs=False)


def test_load_sandbox_settings_independently() -> None:
    settings = load_sandbox_settings(Path("configs/sandbox.yaml"))

    assert settings.image == "evodev-python:3.11"
    assert settings.max_output_chars == 20_000
