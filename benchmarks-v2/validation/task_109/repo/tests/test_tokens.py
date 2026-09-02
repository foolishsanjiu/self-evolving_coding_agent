from datetime import UTC

import pytest
from tokens import parse_token


def test_parser_preserves_token_identity() -> None:
    token = parse_token(
        {"token_id": "session-1", "expires_at": "2026-01-02T03:04:05Z"}
    )

    assert token.token_id == "session-1"
    assert token.expires_at.replace(tzinfo=UTC).year == 2026


def test_parser_rejects_missing_or_malformed_values() -> None:
    with pytest.raises(ValueError, match="invalid token payload"):
        parse_token({"token_id": "missing-expiry"})
    with pytest.raises(ValueError, match="invalid token payload"):
        parse_token({"token_id": "bad", "expires_at": "not-a-date"})
