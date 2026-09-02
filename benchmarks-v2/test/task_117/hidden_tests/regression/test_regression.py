import asyncio

import pytest
from worker_pool import ordered_map


def test_worker_failure_propagates_without_deadlocking_the_pool() -> None:
    failure = RuntimeError("boom")

    async def scenario() -> None:
        async def worker(value: int) -> int:
            if value == 1:
                raise failure
            await asyncio.Event().wait()
            return value

        with pytest.raises(RuntimeError) as caught:
            await asyncio.wait_for(
                ordered_map(worker, [1, 2], limit=1),
                timeout=0.1,
            )
        assert caught.value is failure

    asyncio.run(scenario())


def test_timeout_does_not_cancel_a_completed_result() -> None:
    async def scenario() -> None:
        completed: list[int] = []
        finalized: list[int] = []

        async def worker(value: int) -> int:
            if value == 1:
                completed.append(value)
                return value
            try:
                await asyncio.Event().wait()
            finally:
                finalized.append(value)

        with pytest.raises(TimeoutError):
            await ordered_map(worker, [1, 2], limit=2, timeout=0.01)
        assert completed == [1]
        assert finalized == [2]

    asyncio.run(scenario())
