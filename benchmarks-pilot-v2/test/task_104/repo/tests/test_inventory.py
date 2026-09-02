import pytest
from inventory.errors import InsufficientStockError
from inventory.models import OrderLine
from inventory.service import reserve_order
from inventory.store import InventoryStore


def test_successful_single_line_reservation_is_persisted() -> None:
    store = InventoryStore({"pen": 5})

    reserve_order(store, [OrderLine("pen", 2)])

    assert store.available("pen") == 3


def test_insufficient_single_line_reservation_fails_without_change() -> None:
    store = InventoryStore({"pen": 1})

    with pytest.raises(InsufficientStockError):
        reserve_order(store, [OrderLine("pen", 2)])

    assert store.available("pen") == 1
