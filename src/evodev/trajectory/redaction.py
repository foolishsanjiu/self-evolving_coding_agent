"""Recursive secret filtering applied before trajectory persistence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

REDACTED = "[REDACTED]"


class SecretRedactor:
    """Remove known values, secret fields, headers, and common token patterns."""

    _sensitive_key = re.compile(
        r"(?i)^(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"token|secret|password)$"
    )
    _authorization = re.compile(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;\"']+"
    )
    _assignment = re.compile(
        r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;\"']+"
    )
    _prefixed_token = re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b"
    )
    _jwt = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")

    def __init__(
        self,
        known_secrets: list[str] | None = None,
        env_file: Path | None = None,
    ) -> None:
        secrets = set(known_secrets or [])
        if env_file is not None and env_file.is_file():
            secrets.update(value for value in dotenv_values(env_file).values() if value)
        self.known_secrets = sorted(
            (value for value in secrets if len(value) >= 4),
            key=len,
            reverse=True,
        )

    def redact_text(self, value: str) -> str:
        redacted = value
        for secret in self.known_secrets:
            redacted = redacted.replace(secret, REDACTED)
        redacted = self._authorization.sub(r"\1" + REDACTED, redacted)
        redacted = self._assignment.sub(r"\1" + REDACTED, redacted)
        redacted = self._prefixed_token.sub(REDACTED, redacted)
        return self._jwt.sub(REDACTED, redacted)

    def redact(self, value: Any, key: str | None = None) -> Any:
        if key is not None and self._sensitive_key.fullmatch(key):
            return REDACTED
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                str(item_key): self.redact(item, str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        return value
