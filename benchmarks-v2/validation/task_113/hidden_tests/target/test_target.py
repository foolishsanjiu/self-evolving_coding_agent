from profiles import Profile, dump_profile, load_profile


def test_each_schema_loads_and_dumps_only_its_declared_alias() -> None:
    legacy = {"schema_version": 1, "name": "ada", "displayName": "Ada"}
    current = {"schema_version": 2, "name": "grace", "display_name": "Grace"}

    assert load_profile(legacy) == Profile("ada", "Ada")
    assert load_profile(current) == Profile("grace", "Grace")
    assert dump_profile(Profile("ada", "Ada"), 1) == legacy
    assert dump_profile(Profile("grace", "Grace"), 2) == current


def test_empty_unicode_and_null_values_round_trip_without_truthiness_coercion() -> None:
    values = ["", "研发", None]

    for value in values:
        profile = Profile("user", value)
        for version in (1, 2):
            assert load_profile(dump_profile(profile, version)) == profile
