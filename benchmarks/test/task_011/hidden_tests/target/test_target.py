from pathlib import Path


def test_public_expectation_is_repaired() -> None:
    source = Path("tests/test_strings.py").read_text(encoding="utf-8")
    assert 'reverse_text("abc") == "cba"' in source
