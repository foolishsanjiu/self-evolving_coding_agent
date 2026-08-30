from config_reader import require_name


def test_valid_name_is_trimmed() -> None:
    assert require_name({"name": "  Ada Lovelace  "}) == "Ada Lovelace"
