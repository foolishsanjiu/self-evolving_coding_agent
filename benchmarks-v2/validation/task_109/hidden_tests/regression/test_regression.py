from datetime import UTC, datetime

import pytest
from tokens import Token, is_expired, parse_token


def test_naive_expiry_and_clock_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone offset"):
        parse_token({"token_id": "naive", "expires_at": "2026-04-01T08:00:00"})

    aware = Token("aware", datetime(2026, 4, 1, 8, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="aware clock"):
        is_expired(aware, datetime(2026, 4, 1, 8, 0))


def test_zulu_timestamp_and_non_utc_clock_offset_are_normalized() -> None:
    token = parse_token({"token_id": "zulu", "expires_at": "2026-04-01T08:00:00Z"})
    clock = datetime.fromisoformat("2026-04-01T09:00:01+01:00")

    assert is_expired(token, clock) is True
