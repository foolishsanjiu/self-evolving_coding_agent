from http_cache import CacheEntry, CachingClient, Request, Response, ResponseCache


class RecordingTransport:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.requests: list[Request] = []

    def send(self, request: Request) -> Response:
        self.requests.append(request)
        return self.response


def test_error_response_does_not_replace_existing_cache_entry() -> None:
    cache = ResponseCache()
    request = Request("GET", "https://service.test/data", {})
    original = CacheEntry(b"stable", '"v1"')
    cache.put(request, original)
    transport = RecordingTransport(Response(503, b"down", {"ETag": '"error"'}))

    response = CachingClient(transport, cache).fetch(request)

    assert response.status_code == 503
    assert cache.get(request) == original


def test_conditional_fetch_does_not_mutate_original_request_headers() -> None:
    cache = ResponseCache()
    headers = {"Accept": "application/json", "X-Trace": "abc"}
    request = Request("GET", "https://service.test/data", headers)
    cache.put(request, CacheEntry(b"stable", '"v1"'))
    transport = RecordingTransport(Response(304, b"", {}))

    response = CachingClient(transport, cache).fetch(request)

    assert response.body == b"stable"
    assert headers == {"Accept": "application/json", "X-Trace": "abc"}
    assert transport.requests[0].headers["X-Trace"] == "abc"
