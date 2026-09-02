from resources import run_with_resources


class RecordingResource:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def close(self) -> None:
        self.events.append(f"close:{self.name}")


def test_success_returns_value_and_closes_in_reverse_order() -> None:
    events: list[str] = []
    first = RecordingResource("first", events)
    second = RecordingResource("second", events)

    result = run_with_resources([lambda: first, lambda: second], lambda items: len(items))

    assert result == 2
    assert events == ["close:second", "close:first"]


def test_empty_resource_list_still_runs_operation() -> None:
    assert run_with_resources([], lambda items: items == []) is True
