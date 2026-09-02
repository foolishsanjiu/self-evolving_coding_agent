from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class Resource(Protocol):
    def close(self) -> None: ...


def run_with_resources(
    acquirers: Iterable[Callable[[], Resource]],
    operation: Callable[[list[Resource]], ResultT],
) -> ResultT:
    resources: list[Resource] = []
    try:
        for acquire in acquirers:
            resources.append(acquire())
        return operation(resources)
    finally:
        for resource in reversed(resources):
            resource.close()
