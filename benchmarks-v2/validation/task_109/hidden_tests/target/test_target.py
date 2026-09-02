from datetime import UTC, datetime

from tokens import is_expired, parse_token


def test_offset_timestamp_is_compared_as_the_same_utc_instant() -> None:
    token = parse_token(
        {"token_id": "offset", "expires_at": "2026-04-01T10:00:00+02:00"}
    )

    assert token.expires_at == datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    assert token.expires_at.tzinfo is UTC
    assert is_expired(token, datetime(2026, 4, 1, 7, 59, 59, tzinfo=UTC)) is False


def test_exact_expiry_boundary_is_expired() -> None:
    token = parse_token(
        {"token_id": "boundary", "expires_at": "2026-04-01T10:00:00+02:00"}
    )

    assert is_expired(token, datetime(2026, 4, 1, 8, 0, tzinfo=UTC)) is True
