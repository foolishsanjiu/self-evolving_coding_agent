import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


async def ordered_map(
    worker: Callable[[InputT], Awaitable[OutputT]],
    values: Sequence[InputT],
    *,
    limit: int,
    timeout: float | None = None,
) -> list[OutputT]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if not values:
        return []
    semaphore = asyncio.Semaphore(limit)

    async def run(value: InputT) -> OutputT:
        await semaphore.acquire()
        result = await worker(value)
        semaphore.release()
        return result

    tasks = [asyncio.create_task(run(value)) for value in values]
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        raise TimeoutError("worker pool timed out")
    return [task.result() for task in tasks]
