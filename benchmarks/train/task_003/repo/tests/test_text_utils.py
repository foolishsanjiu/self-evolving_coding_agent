from text_utils import slugify


def test_slugifies_words() -> None:
    assert slugify("Hello World") == "hello-world"
