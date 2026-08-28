"""Validated YAML and environment configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class ModelSettings(BaseModel):
    """Settings for an OpenAI-compatible model endpoint."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(default=0.1, ge=0, le=2)
    base_url: str | None = None
    api_key_env: str = Field(min_length=1)

    def resolve_api_key(self) -> str:
        """Read the API key at call time without storing it in serialized settings."""
        value = os.getenv(self.api_key_env)
        if not value:
            raise ValueError(f"Required environment variable is not set: {self.api_key_env}")
        return value


class AgentSettings(BaseModel):
    """Stable runtime limits for the initial agent."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=15, gt=0)
    max_tool_retries: int = Field(default=1, ge=0)
    max_context_chars: int = Field(default=60_000, gt=0)


class AppSettings(BaseModel):
    """Validated application settings."""

    model_config = ConfigDict(extra="forbid")

    model: ModelSettings
    agent: AgentSettings


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must contain a YAML mapping: {path}")
    return data


def load_settings(config_dir: Path, env_file: Path | None = None) -> AppSettings:
    """Load optional environment variables and validate both YAML files."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    return AppSettings.model_validate(
        {
            "model": _read_yaml(config_dir / "model.yaml"),
            "agent": _read_yaml(config_dir / "agent.yaml"),
        }
    )
