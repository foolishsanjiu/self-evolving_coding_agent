from catalog.cache import ProductViewCache
from catalog.repository import CatalogRepository
from catalog.service import CatalogService


def test_exact_request_still_hits_cache() -> None:
    repository = CatalogRepository()
    service = CatalogService(repository, ProductViewCache())

    expected = service.product_view("notebook", "zh", True)
    actual = service.product_view("notebook", "zh", True)

    assert actual is expected
    assert repository.build_count == 1


def test_cache_entries_remain_separate_across_products() -> None:
    repository = CatalogRepository()
    service = CatalogService(repository, ProductViewCache())

    service.product_view("pencil", "en", False)
    service.product_view("notebook", "en", False)

    assert repository.build_count == 2
