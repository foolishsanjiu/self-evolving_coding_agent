import pytest
from retries import RequestError, request_with_retries


def test_final_transient_error_is_raised_without_sleeping_again() -> None:
    first = RequestError("first", status_code=503)
    final = RequestError("final", status_code=503)
    errors = iter([first, final])
    sleeps: list[float] = []

    with pytest.raises(RequestError) as caught:
        request_with_retries(
            lambda: (_ for _ in ()).throw(next(errors)),
            max_attempts=2,
            backoff=lambda attempt: float(attempt),
            sleeper=sleeps.append,
        )

    assert caught.value is final
    assert sleeps == [1.0]


def test_request_timeout_status_is_transient() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestError("timeout", status_code=408)
        return "ok"

    assert request_with_retries(
        operation,
        max_attempts=2,
        backoff=lambda attempt: 0.0,
        sleeper=lambda delay: None,
    ) == "ok"
