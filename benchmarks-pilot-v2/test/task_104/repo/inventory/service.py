from collections.abc import Iterable

from inventory.models import OrderLine
from inventory.store import InventoryStore


def reserve_order(store: InventoryStore, lines: Iterable[OrderLine]) -> None:
    for line in lines:
        store.reserve(line.sku, line.quantity)
