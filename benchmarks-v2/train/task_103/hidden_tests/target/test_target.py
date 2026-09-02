import pytest
from settings.resolver import build_settings


def test_environment_overrides_file_values() -> None:
    result = build_settings(
        {},
        {"timeout": "12", "region": "env-region"},
        {"timeout": 45, "region": "file-region"},
    )

    assert result.timeout == 12
    assert result.region == "env-region"


def test_false_like_environment_boolean_is_normalized() -> None:
    assert build_settings({}, {"debug": "false"}, {}).debug is False
    assert build_settings({}, {"debug": "YES"}, {}).debug is True


def test_cli_false_and_zero_are_valid_overrides() -> None:
    result = build_settings(
        {"debug": False, "timeout": 0},
        {"debug": "true", "timeout": "20"},
        {},
    )

    assert result.debug is False
    assert result.timeout == 0


def test_invalid_boolean_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid boolean"):
        build_settings({}, {"debug": "sometimes"}, {})
