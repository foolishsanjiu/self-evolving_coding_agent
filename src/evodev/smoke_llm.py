"""Run one real model call to verify local provider configuration."""

from __future__ import annotations

from pathlib import Path

from evodev.config import load_settings
from evodev.llm import LLMClient
from evodev.logging_config import configure_logging


def main() -> None:
    configure_logging()
    settings = load_settings(Path("configs"), env_file=Path(".env"))
    turn = LLMClient(settings.model).generate(
        [{"role": "user", "content": "Reply with exactly: EvoDev ready"}]
    )
    print(turn.content or "")


if __name__ == "__main__":
    main()
