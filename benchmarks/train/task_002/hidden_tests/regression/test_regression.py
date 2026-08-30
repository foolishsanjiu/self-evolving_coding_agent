from ports import parse_port


def test_boundary_ports() -> None:
    assert parse_port("1") == 1
    assert parse_port("65535") == 65535
