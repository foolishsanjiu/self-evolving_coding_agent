import pytest
from inventory.errors import InsufficientStockError
from inventory.models import OrderLine
from inventory.service import reserve_order
from inventory.store import InventoryStore


def test_later_failure_restores_all_earlier_lines() -> None:
    store = InventoryStore({"pen": 5, "book": 1, "bag": 4})

    with pytest.raises(InsufficientStockError, match="book"):
        reserve_order(
            store,
            [OrderLine("pen", 2), OrderLine("bag", 1), OrderLine("book", 2)],
        )

    assert store.available("pen") == 5
    assert store.available("bag") == 4
    assert store.available("book") == 1


def test_repeated_sku_is_fully_restored_after_failure() -> None:
    store = InventoryStore({"pen": 5})

    with pytest.raises(InsufficientStockError):
        reserve_order(store, [OrderLine("pen", 3), OrderLine("pen", 3)])

    assert store.available("pen") == 5
