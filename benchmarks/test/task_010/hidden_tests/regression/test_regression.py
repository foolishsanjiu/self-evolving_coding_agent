from ranges import merge_ranges


def test_empty_and_single_ranges() -> None:
    assert merge_ranges([]) == []
    assert merge_ranges([(4, 5)]) == [(4, 5)]
