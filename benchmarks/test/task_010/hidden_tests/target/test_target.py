from ranges import merge_ranges


def test_unsorted_touching_and_disjoint_ranges() -> None:
    assert merge_ranges([(10, 12), (2, 3), (1, 1), (6, 8), (8, 9)]) == [
        (1, 3),
        (6, 12),
    ]
