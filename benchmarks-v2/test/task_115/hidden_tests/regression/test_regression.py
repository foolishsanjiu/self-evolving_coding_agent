import pytest
from packages import Package, installation_order


def test_duplicate_package_definitions_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate package: core"):
        installation_order([Package("core"), Package("core")])


def test_repeated_dependencies_do_not_duplicate_output() -> None:
    packages = [Package("app", ("core", "core")), Package("core")]

    assert installation_order(packages) == ["core", "app"]


def test_independent_order_is_not_alphabetically_resorted() -> None:
    packages = [Package("zeta"), Package("alpha"), Package("middle")]

    assert installation_order(packages) == ["zeta", "alpha", "middle"]
