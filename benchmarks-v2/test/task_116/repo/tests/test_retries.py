from retries import RequestError, request_with_retries


def test_success_does_not_sleep() -> None:
    sleeps: list[float] = []

    result = request_with_retries(
        lambda: "ok",
        max_attempts=3,
        backoff=lambda attempt: float(attempt),
        sleeper=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == []


def test_transient_failure_uses_backoff_before_retry() -> None:
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestError("busy", status_code=503)
        return "ok"

    result = request_with_retries(
        operation,
        max_attempts=3,
        backoff=lambda attempt: attempt * 0.25,
        sleeper=sleeps.append,
    )

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [0.25]
