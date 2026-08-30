from sequence import median


def test_even_length_median() -> None:
    assert median([1, 3, 7, 9]) == 5
