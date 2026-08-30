from orders import order_total


def test_discount_then_percentage_tax() -> None:
    assert order_total(100, 20, 10) == 88
