from pathlib import Path

import pytest
from pydantic import ValidationError

from evodev.config import ModelSettings, load_settings


def test_load_settings_and_resolve_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value")

    settings = load_settings(Path("configs"))

    assert settings.model.model == "deepseek-chat"
    assert settings.agent.max_steps == 15
    assert settings.model.resolve_api_key() == "secret-value"
    assert "secret-value" not in settings.model.model_dump_json()


def test_invalid_model_config_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSettings(
            provider="deepseek",
            model="deepseek-chat",
            temperature=3,
            api_key_env="DEEPSEEK_API_KEY",
        )


def test_missing_api_key_has_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        load_settings(Path("configs")).model.resolve_api_key()
