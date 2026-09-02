from profiles import Profile, load_profile


def test_v2_profile_loads_canonical_name() -> None:
    profile = load_profile(
        {"schema_version": 2, "name": "ada", "display_name": "Ada Lovelace"}
    )

    assert profile == Profile(name="ada", display_name="Ada Lovelace")


def test_profile_model_preserves_optional_display_name() -> None:
    assert Profile(name="anonymous", display_name=None).display_name is None
