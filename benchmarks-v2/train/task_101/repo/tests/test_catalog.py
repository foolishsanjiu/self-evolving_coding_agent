from catalog.cache import ProductViewCache
from catalog.repository import CatalogRepository
from catalog.service import CatalogService


def test_identical_request_uses_cached_view() -> None:
    repository = CatalogRepository()
    service = CatalogService(repository, ProductViewCache())

    first = service.product_view("pencil", "en", False)
    second = service.product_view("pencil", "en", False)

    assert first == second
    assert repository.build_count == 1


def test_different_products_have_independent_entries() -> None:
    service = CatalogService(CatalogRepository(), ProductViewCache())

    assert service.product_view("pencil", "en", False).title == "Pencil"
    assert service.product_view("notebook", "en", False).title == "Notebook"
