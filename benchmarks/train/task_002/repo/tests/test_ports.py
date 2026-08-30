from ports import parse_port


def test_valid_port() -> None:
    assert parse_port("8080") == 8080
