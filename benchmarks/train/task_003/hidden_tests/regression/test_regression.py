from text_utils import slugify


def test_empty_and_already_normalized_values() -> None:
    assert slugify("") == ""
    assert slugify("ready") == "ready"
