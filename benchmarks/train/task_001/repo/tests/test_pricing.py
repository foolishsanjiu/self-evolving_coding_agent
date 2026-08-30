from pricing import discounted_price


def test_zero_discount_preserves_price() -> None:
    assert discounted_price(50, 0) == 50
