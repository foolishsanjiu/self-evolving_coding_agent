from sequence import median


def test_unsorted_odd_sequence() -> None:
    assert median([8, 2, 4, 1, 3]) == 3
