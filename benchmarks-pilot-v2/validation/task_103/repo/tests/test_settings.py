from settings.resolver import build_settings


def test_cli_region_wins_when_all_sources_define_it() -> None:
    result = build_settings(
        {"region": "cli-region"},
        {"region": "env-region"},
        {"region": "file-region"},
    )

    assert result.region == "cli-region"


def test_missing_values_use_typed_defaults() -> None:
    result = build_settings({}, {}, {})

    assert result.timeout == 30
    assert result.debug is False
    assert result.region == "us-east"
