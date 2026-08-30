from pricing import discounted_price


def test_zero_discount_regression() -> None:
    assert discounted_price(12.5, 0) == 12.5
