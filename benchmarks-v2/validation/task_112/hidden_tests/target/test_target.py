import pytest
from resources import run_with_resources


class FailingResource:
    def __init__(self, name: str, events: list[str], close_error: Exception | None) -> None:
        self.name = name
        self.events = events
        self.close_error = close_error

    def close(self) -> None:
        self.events.append(f"close:{self.name}")
        if self.close_error is not None:
            raise self.close_error


def test_primary_operation_failure_is_preserved_after_all_cleanup_attempts() -> None:
    events: list[str] = []
    primary = RuntimeError("operation failed")
    first = FailingResource("first", events, ValueError("first close"))
    second = FailingResource("second", events, OSError("second close"))

    with pytest.raises(RuntimeError) as captured:
        run_with_resources(
            [lambda: first, lambda: second],
            lambda resources: (_ for _ in ()).throw(primary),
        )

    assert captured.value is primary
    assert events == ["close:second", "close:first"]
    assert isinstance(captured.value.__cause__, ExceptionGroup)
    assert len(captured.value.__cause__.exceptions) == 2


def test_acquisition_failure_cleans_only_resources_already_acquired() -> None:
    events: list[str] = []
    first = FailingResource("first", events, None)
    primary = LookupError("second acquire failed")

    with pytest.raises(LookupError) as captured:
        run_with_resources(
            [lambda: first, lambda: (_ for _ in ()).throw(primary)],
            lambda resources: None,
        )

    assert captured.value is primary
    assert events == ["close:first"]
