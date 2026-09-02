from http_cache import CachingClient, Request, Response, ResponseCache


class SequenceTransport:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = iter(responses)
        self.requests: list[Request] = []

    def send(self, request: Request) -> Response:
        self.requests.append(request)
        return next(self.responses)


def test_etag_refresh_reuses_cached_body_on_not_modified() -> None:
    transport = SequenceTransport(
        [
            Response(200, b"cached", {"ETag": '"v1"'}),
            Response(304, b"", {}),
        ]
    )
    request = Request("GET", "https://service.test/profile", {"Accept": "application/json"})
    client = CachingClient(transport, ResponseCache())

    first = client.fetch(request)
    second = client.fetch(request)

    assert first.body == second.body == b"cached"
    assert second.status_code == 200
    assert "If-None-Match" not in transport.requests[0].headers
    assert transport.requests[1].headers["If-None-Match"] == '"v1"'


def test_fresh_200_replaces_cached_body_and_etag_together() -> None:
    transport = SequenceTransport(
        [
            Response(200, b"old", {"ETag": '"v1"'}),
            Response(200, b"new", {"ETag": '"v2"'}),
            Response(304, b"", {}),
        ]
    )
    request = Request("GET", "https://service.test/profile", {})
    client = CachingClient(transport, ResponseCache())

    client.fetch(request)
    assert client.fetch(request).body == b"new"
    assert client.fetch(request).body == b"new"
    assert transport.requests[2].headers["If-None-Match"] == '"v2"'
