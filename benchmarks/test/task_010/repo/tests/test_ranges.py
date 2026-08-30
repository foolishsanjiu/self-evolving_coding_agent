from ranges import merge_ranges


def test_overlapping_ranges() -> None:
    assert merge_ranges([(1, 4), (3, 7)]) == [(1, 7)]
