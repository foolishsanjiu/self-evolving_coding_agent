import pytest
from ports import parse_port


def test_non_integer_has_clear_error() -> None:
    with pytest.raises(ValueError, match="port must be an integer"):
        parse_port("http")


def test_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="port must be between 1 and 65535"):
        parse_port("70000")
