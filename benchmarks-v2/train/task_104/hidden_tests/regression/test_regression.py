import pytest
from inventory.models import OrderLine
from inventory.service import reserve_order
from inventory.store import InventoryStore


def test_successful_multi_line_order_keeps_all_reservations() -> None:
    store = InventoryStore({"pen": 5, "book": 4})

    reserve_order(store, [OrderLine("pen", 2), OrderLine("book", 3)])

    assert store.available("pen") == 3
    assert store.available("book") == 1


def test_existing_reservation_is_not_rolled_back() -> None:
    store = InventoryStore({"pen": 8, "book": 1})
    store.reserve("pen", 2)

    with pytest.raises(ValueError, match="book"):
        reserve_order(store, [OrderLine("pen", 3), OrderLine("book", 2)])

    assert store.available("pen") == 6
    assert store.available("book") == 1


def test_validation_error_also_rolls_back_prior_lines() -> None:
    store = InventoryStore({"pen": 5, "book": 5})

    with pytest.raises(ValueError, match="positive"):
        reserve_order(store, [OrderLine("pen", 2), OrderLine("book", 0)])

    assert store.available("pen") == 5
    assert store.available("book") == 5
