import asyncio
from contextlib import suppress

from worker_pool import ordered_map


def test_timeout_cancels_and_awaits_every_outstanding_worker() -> None:
    async def scenario() -> None:
        started: set[int] = set()
        finalized: set[int] = set()

        async def worker(value: int) -> int:
            started.add(value)
            try:
                await asyncio.Event().wait()
            finally:
                finalized.add(value)

        try:
            await ordered_map(worker, [1, 2], limit=2, timeout=0.01)
        except TimeoutError:
            pass
        else:
            raise AssertionError("timeout was not raised")
        assert started == {1, 2}
        assert finalized == {1, 2}

    asyncio.run(scenario())


def test_parent_cancellation_cleans_up_child_workers() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        finalized: set[int] = set()

        async def worker(value: int) -> int:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finalized.add(value)

        pool = asyncio.create_task(ordered_map(worker, [1, 2], limit=2))
        await started.wait()
        pool.cancel()
        with suppress(asyncio.CancelledError):
            await pool
        assert finalized == {1, 2}

    asyncio.run(scenario())
