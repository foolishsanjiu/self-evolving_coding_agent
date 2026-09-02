"""Run one real model call to verify local provider configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

from evodev.config import load_settings
from evodev.llm import LLMClient
from evodev.logging_config import configure_logging


def require_smoke_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("LLM smoke test requires --confirm-paid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one paid LLM configuration smoke test.")
    parser.add_argument("--confirm-paid", action="store_true")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    require_smoke_paid_confirmation(arguments.confirm_paid)
    configure_logging()
    settings = load_settings(Path("configs"), env_file=Path(".env"))
    turn = LLMClient(settings.model).generate(
        [{"role": "user", "content": "Reply with exactly: EvoDev ready"}]
    )
    print(turn.content or "")


if __name__ == "__main__":
    main()
