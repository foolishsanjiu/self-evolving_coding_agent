from strings import reverse_text


def test_reverse_implementation_stays_correct() -> None:
    assert reverse_text("EvoDev") == "veDovE"
    assert reverse_text("") == ""
