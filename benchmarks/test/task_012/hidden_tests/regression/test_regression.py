from orders import order_total
from tax import add_tax


def test_discount_floor_and_direct_tax() -> None:
    assert order_total(10, 20, 10) == 0
    assert add_tax(50, 5) == 52.5
