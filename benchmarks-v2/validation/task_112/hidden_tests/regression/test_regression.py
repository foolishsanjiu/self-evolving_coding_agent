import pytest
from resources import run_with_resources


class Resource:
    def __init__(self, name: str, events: list[str], error: Exception | None = None) -> None:
        self.name = name
        self.events = events
        self.error = error

    def close(self) -> None:
        self.events.append(self.name)
        if self.error is not None:
            raise self.error


def test_cleanup_error_surfaces_when_operation_succeeds() -> None:
    events: list[str] = []
    expected = ValueError("close failed")

    with pytest.raises(ValueError) as captured:
        run_with_resources([lambda: Resource("only", events, expected)], lambda items: 7)

    assert captured.value is expected
    assert events == ["only"]


def test_successful_cleanup_preserves_operation_result() -> None:
    events: list[str] = []

    result = run_with_resources(
        [lambda: Resource("first", events), lambda: Resource("second", events)],
        lambda items: "done",
    )

    assert result == "done"
    assert events == ["second", "first"]
