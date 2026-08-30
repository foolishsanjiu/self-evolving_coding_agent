from pricing import discounted_price


def test_percentage_discount() -> None:
    assert discounted_price(50, 20) == 40
