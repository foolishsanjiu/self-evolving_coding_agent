from math_utils import is_even


def test_implementation_remains_correct() -> None:
    assert is_even(2)
    assert not is_even(3)
