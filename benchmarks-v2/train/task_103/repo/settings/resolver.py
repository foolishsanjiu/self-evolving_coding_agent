from collections.abc import Mapping

from settings.coercion import coerce_value
from settings.defaults import DEFAULTS
from settings.models import AppSettings


def resolve_value(
    name: str,
    cli: Mapping[str, object],
    environment: Mapping[str, object],
    file_values: Mapping[str, object],
) -> object:
    if name not in DEFAULTS:
        raise KeyError(name)
    for source in (cli, file_values, environment, DEFAULTS):
        if name in source:
            return coerce_value(name, source[name])
    raise AssertionError("default configuration is incomplete")


def build_settings(
    cli: Mapping[str, object],
    environment: Mapping[str, object],
    file_values: Mapping[str, object],
) -> AppSettings:
    return AppSettings(
        timeout=resolve_value("timeout", cli, environment, file_values),
        debug=resolve_value("debug", cli, environment, file_values),
        region=resolve_value("region", cli, environment, file_values),
    )
