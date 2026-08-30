from text_utils import slugify


def test_collapses_punctuation_and_spacing() -> None:
    assert slugify("  Red, green... BLUE! ") == "red-green-blue"
