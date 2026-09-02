from concurrent.futures import ThreadPoolExecutor

import pytest
from parallelism import ordered_parallel_map


class RecordingExecutor:
    def __init__(self, *, max_workers: int) -> None:
        self.inner = ThreadPoolExecutor(max_workers=max_workers)
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(self, function, item):
        return self.inner.submit(function, item)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.shutdown_calls.append((wait, cancel_futures))
        self.inner.shutdown(wait=wait, cancel_futures=cancel_futures)


def test_executor_shutdown_cancels_pending_work_on_success() -> None:
    executors: list[RecordingExecutor] = []

    def factory(*, max_workers: int) -> RecordingExecutor:
        executor = RecordingExecutor(max_workers=max_workers)
        executors.append(executor)
        return executor

    assert ordered_parallel_map(lambda value: value + 1, [1, 2], executor_factory=factory) == [
        2,
        3,
    ]
    assert executors[0].shutdown_calls == [(True, True)]


def test_executor_shutdown_cancels_pending_work_on_failure() -> None:
    executors: list[RecordingExecutor] = []

    def factory(*, max_workers: int) -> RecordingExecutor:
        executor = RecordingExecutor(max_workers=max_workers)
        executors.append(executor)
        return executor

    def fail(value: int) -> int:
        raise LookupError(value)

    with pytest.raises(LookupError):
        ordered_parallel_map(fail, [1, 2, 3], max_workers=1, executor_factory=factory)
    assert executors[0].shutdown_calls == [(True, True)]
