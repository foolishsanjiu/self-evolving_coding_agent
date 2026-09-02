from collections.abc import Callable
from typing import TypeVar

from retries.errors import RequestError

ResultT = TypeVar("ResultT")


def request_with_retries(
    operation: Callable[[], ResultT],
    *,
    max_attempts: int,
    backoff: Callable[[int], float],
    sleeper: Callable[[float], None],
) -> ResultT:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except RequestError:
            sleeper(backoff(attempt))
    raise RuntimeError("request failed after retries")
