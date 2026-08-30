from cart import cart_total


def test_empty_and_undiscounted_carts() -> None:
    assert cart_total([], 25) == 0
    assert cart_total([10, 20], 0) == 30
