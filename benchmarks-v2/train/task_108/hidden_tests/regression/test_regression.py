import pytest
from transport import dispatch_request


class BrokenImplementation:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, *, method, url, headers, timeout):
        self.calls += 1
        raise TypeError("bug inside transport")


class UnsupportedTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, payload):
        self.calls += 1
        return payload


def test_transport_type_error_is_not_retried_as_a_legacy_call() -> None:
    transport = BrokenImplementation()

    with pytest.raises(TypeError, match="bug inside transport"):
        dispatch_request(
            transport,
            method="GET",
            url="https://service.test",
            headers={"Accept": "application/json"},
            timeout=3.0,
        )
    assert transport.calls == 1


def test_unsupported_signature_is_rejected_before_invocation() -> None:
    transport = UnsupportedTransport()

    with pytest.raises(TypeError, match="unsupported transport.send signature"):
        dispatch_request(
            transport,
            method="GET",
            url="https://service.test",
            headers={},
            timeout=1.0,
        )
    assert transport.calls == 0
