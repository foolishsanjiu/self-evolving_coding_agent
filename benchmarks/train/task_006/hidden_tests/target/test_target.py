from cart import cart_total


def test_discount_applies_to_every_item() -> None:
    assert cart_total([50, 30, 20], 10) == 90
