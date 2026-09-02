import threading
import time

import pytest
from parallelism import ordered_parallel_map


def test_results_preserve_input_order_while_workers_are_bounded() -> None:
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def work(value: int) -> int:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep((4 - value) * 0.01)
        with lock:
            active -= 1
        return value * 10

    assert ordered_parallel_map(work, [1, 2, 3], max_workers=2) == [10, 20, 30]
    assert maximum_active == 2


def test_worker_exception_is_propagated_without_replacement() -> None:
    expected = RuntimeError("worker failed")

    def work(value: int) -> int:
        if value == 2:
            raise expected
        return value

    with pytest.raises(RuntimeError) as captured:
        ordered_parallel_map(work, [1, 2, 3], max_workers=2)
    assert captured.value is expected
