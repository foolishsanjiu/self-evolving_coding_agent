from catalog.models import ProductView


class ProductViewCache:
    def __init__(self) -> None:
        self._values: dict[str, ProductView] = {}

    def get(self, product_id: str) -> ProductView | None:
        return self._values.get(product_id)

    def put(self, product_id: str, view: ProductView) -> None:
        self._values[product_id] = view
