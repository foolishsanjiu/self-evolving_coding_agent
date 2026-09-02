from collections.abc import Mapping

from transport import Response, dispatch_request


class KeywordOnlyTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Response:
        self.calls.append((method, url, dict(headers), timeout))
        return Response(200, b"current")


class LegacyTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(self, method, url, headers, timeout, /) -> Response:
        self.calls.append((method, url, dict(headers), timeout))
        return Response(200, b"legacy")


def test_current_keyword_only_transport_receives_exact_request_fields() -> None:
    transport = KeywordOnlyTransport()

    response = dispatch_request(
        transport,
        method="POST",
        url="https://service.test/items",
        headers={"X-Trace": "abc"},
        timeout=2.5,
    )

    assert response.body == b"current"
    assert transport.calls == [
        ("POST", "https://service.test/items", {"X-Trace": "abc"}, 2.5)
    ]


def test_recognized_legacy_positional_transport_remains_supported() -> None:
    transport = LegacyTransport()

    response = dispatch_request(
        transport,
        method="GET",
        url="https://legacy.test",
        headers={},
        timeout=1.0,
    )

    assert response.body == b"legacy"
    assert len(transport.calls) == 1
