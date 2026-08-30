from sequence import median


def test_odd_length_median() -> None:
    assert median([9, 1, 5]) == 5
