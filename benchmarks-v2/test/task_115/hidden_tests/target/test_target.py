import pytest
from packages import Package, installation_order


def test_dependencies_precede_dependants_with_stable_branches() -> None:
    packages = [
        Package("app", ("core", "ui")),
        Package("tools", ("core",)),
        Package("ui", ("core",)),
        Package("core"),
    ]

    assert installation_order(packages) == ["core", "ui", "app", "tools"]


def test_missing_dependency_names_package_and_dependant() -> None:
    with pytest.raises(ValueError, match="missing dependency 'core'.*'app'"):
        installation_order([Package("app", ("core",))])


def test_cycle_error_contains_a_concrete_closed_path() -> None:
    packages = [
        Package("api", ("db",)),
        Package("db", ("schema",)),
        Package("schema", ("api",)),
    ]

    with pytest.raises(ValueError, match="api -> db -> schema -> api"):
        installation_order(packages)
