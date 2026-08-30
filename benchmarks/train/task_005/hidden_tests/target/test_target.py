from pathlib import Path


def test_public_odd_assertion_is_repaired() -> None:
    source = Path("tests/test_math_utils.py").read_text(encoding="utf-8")
    assert "assert not is_even(3)" in source
