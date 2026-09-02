import pytest
from parallelism import ordered_parallel_map


def test_empty_input_returns_without_constructing_an_executor() -> None:
    def fail_factory(**kwargs):
        raise AssertionError(f"executor should not be created: {kwargs}")

    assert ordered_parallel_map(str, [], executor_factory=fail_factory) == []


def test_worker_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        ordered_parallel_map(str, [1], max_workers=0)


def test_single_item_returns_its_result() -> None:
    assert ordered_parallel_map(lambda value: value * 2, [3], max_workers=1) == [6]
