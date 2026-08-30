from orders import order_total


def test_zero_tax_order() -> None:
    assert order_total(100, 20, 0) == 80
