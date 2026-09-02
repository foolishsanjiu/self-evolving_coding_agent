import pytest
from settings.resolver import build_settings, resolve_value


def test_file_values_still_override_defaults() -> None:
    result = build_settings({}, {}, {"timeout": "9", "debug": "on"})

    assert result.timeout == 9
    assert result.debug is True


def test_inputs_are_not_mutated() -> None:
    cli = {"region": "local"}
    environment = {"debug": "true"}
    file_values = {"timeout": 8}

    build_settings(cli, environment, file_values)

    assert cli == {"region": "local"}
    assert environment == {"debug": "true"}
    assert file_values == {"timeout": 8}


def test_unknown_setting_remains_an_error() -> None:
    with pytest.raises(KeyError, match="unknown"):
        resolve_value("unknown", {}, {}, {})
