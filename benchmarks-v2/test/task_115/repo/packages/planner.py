from packages.models import Package


def installation_order(packages: list[Package]) -> list[str]:
    return [package.name for package in packages]
