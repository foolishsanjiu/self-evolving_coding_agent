import asyncio

from worker_pool import ordered_map


def test_success_is_bounded_and_input_ordered() -> None:
    async def scenario() -> tuple[list[int], int]:
        active = 0
        peak = 0

        async def worker(value: int) -> int:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep((4 - value) * 0.001)
            active -= 1
            return value * 10

        return await ordered_map(worker, [1, 2, 3], limit=2), peak

    results, peak = asyncio.run(scenario())

    assert results == [10, 20, 30]
    assert peak == 2


def test_empty_input_returns_immediately() -> None:
    async def worker(value: int) -> int:
        return value

    assert asyncio.run(ordered_map(worker, [], limit=1)) == []
