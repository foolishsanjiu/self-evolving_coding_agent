from catalog.cache import ProductViewCache
from catalog.repository import CatalogRepository
from catalog.service import CatalogService


def test_locale_is_part_of_the_cache_identity() -> None:
    service = CatalogService(CatalogRepository(), ProductViewCache())

    english = service.product_view("pencil", "en", False)
    chinese = service.product_view("pencil", "zh", False)

    assert english.title == "Pencil"
    assert chinese.title == "Pencil (ZH)"


def test_tax_mode_is_part_of_the_cache_identity() -> None:
    service = CatalogService(CatalogRepository(), ProductViewCache())

    net = service.product_view("notebook", "en", False)
    gross = service.product_view("notebook", "en", True)

    assert net.total == 25.0
    assert gross.total == 27.5
