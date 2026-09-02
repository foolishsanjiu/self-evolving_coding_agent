import pytest
from retries import RequestError, request_with_retries


def test_permanent_failure_is_not_retried() -> None:
    error = RequestError("bad request", status_code=400)
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(RequestError) as caught:
        request_with_retries(
            operation,
            max_attempts=4,
            backoff=lambda attempt: float(attempt),
            sleeper=sleeps.append,
        )

    assert caught.value is error
    assert attempts == 1
    assert sleeps == []


def test_retry_after_precedes_backoff_for_rate_limit() -> None:
    attempts = 0
    backoff_calls: list[int] = []
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestError("limited", status_code=429, retry_after="1.5")
        return "ok"

    result = request_with_retries(
        operation,
        max_attempts=2,
        backoff=lambda attempt: backoff_calls.append(attempt) or 9.0,
        sleeper=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == [1.5]
    assert backoff_calls == []


def test_invalid_retry_after_falls_back_to_attempt_number() -> None:
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestError("busy", status_code=503, retry_after="later")
        return "ok"

    assert request_with_retries(
        operation,
        max_attempts=2,
        backoff=lambda attempt: attempt * 2.0,
        sleeper=sleeps.append,
    ) == "ok"
    assert sleeps == [2.0]
