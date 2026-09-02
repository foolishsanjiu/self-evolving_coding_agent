import pytest
from profiles import Profile, dump_profile, load_profile


def test_conflicting_aliases_are_rejected_for_every_version() -> None:
    for version in (1, 2):
        with pytest.raises(ValueError, match="conflicting display name aliases"):
            load_profile(
                {
                    "schema_version": version,
                    "name": "user",
                    "displayName": "legacy",
                    "display_name": "current",
                }
            )


def test_unknown_versions_are_rejected_on_load_and_dump() -> None:
    with pytest.raises(ValueError, match="unsupported schema version"):
        load_profile({"schema_version": 3, "name": "user"})
    with pytest.raises(ValueError, match="unsupported schema version"):
        dump_profile(Profile("user", None), 3)


def test_name_is_not_coerced_from_an_unrelated_type() -> None:
    with pytest.raises(ValueError, match="profile name must be a string"):
        load_profile({"schema_version": 2, "name": 123, "display_name": None})
