from catalog.cache import ProductViewCache
from catalog.models import ProductView
from catalog.repository import CatalogRepository


class CatalogService:
    def __init__(self, repository: CatalogRepository, cache: ProductViewCache) -> None:
        self.repository = repository
        self.cache = cache

    def product_view(
        self, product_id: str, locale: str, include_tax: bool
    ) -> ProductView:
        cached = self.cache.get(product_id)
        if cached is not None:
            return cached
        view = self.repository.build_view(product_id, locale, include_tax)
        self.cache.put(product_id, view)
        return view
