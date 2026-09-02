from packages import Package, installation_order


def test_independent_packages_keep_input_order() -> None:
    packages = [Package("cli"), Package("docs"), Package("server")]

    assert installation_order(packages) == ["cli", "docs", "server"]


def test_dependency_declarations_are_deduplicated() -> None:
    package = Package("app", ("core", "core", "ui", "core"))

    assert package.dependencies == ("core", "ui")


def test_empty_inventory_has_empty_plan() -> None:
    assert installation_order([]) == []
