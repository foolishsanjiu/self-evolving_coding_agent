from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


def ordered_parallel_map(
    function: Callable[[InputT], OutputT],
    items: Iterable[InputT],
    max_workers: int = 4,
    *,
    executor_factory=ThreadPoolExecutor,
) -> list[OutputT]:
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    values = list(items)
    if not values:
        return []
    with executor_factory(max_workers=max_workers) as executor:
        futures = [executor.submit(function, item) for item in values]
        return [future.result() for future in as_completed(futures)]
