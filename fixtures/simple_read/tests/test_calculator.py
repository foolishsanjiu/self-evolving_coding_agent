from src.calculator import add


def test_add() -> None:
    assert add(2, 3) == 5
