from inventory.errors import InsufficientStockError


class InventoryStore:
    def __init__(self, available: dict[str, int]) -> None:
        self._available = dict(available)

    def available(self, sku: str) -> int:
        return self._available.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.available(sku) < quantity:
            raise InsufficientStockError(f"insufficient stock for {sku}")
        self._available[sku] -= quantity

    def release(self, sku: str, quantity: int) -> None:
        self._available[sku] = self.available(sku) + quantity
