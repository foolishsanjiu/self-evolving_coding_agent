from cart import cart_total


def test_single_item_cart() -> None:
    assert cart_total([100], 10) == 90
