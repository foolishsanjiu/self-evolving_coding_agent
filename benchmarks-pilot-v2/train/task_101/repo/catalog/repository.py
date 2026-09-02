class CatalogRepository:
    def __init__(self) -> None:
        self.build_count = 0
        self._titles = {
            "pencil": {"en": "Pencil", "zh": "Pencil (ZH)"},
            "notebook": {"en": "Notebook", "zh": "Notebook (ZH)"},
        }
        self._prices = {"pencil": 10.0, "notebook": 25.0}

    def build_view(self, product_id: str, locale: str, include_tax: bool):
        from catalog.models import ProductView

        self.build_count += 1
        title = self._titles[product_id][locale]
        price = self._prices[product_id]
        total = round(price * 1.1, 2) if include_tax else price
        return ProductView(product_id=product_id, title=title, total=total)
