from http_cache import CacheEntry, CachingClient, Request, Response, ResponseCache


class StaticTransport:
    def __init__(self, response: Response) -> None:
        self.response = response

    def send(self, request: Request) -> Response:
        return self.response


def test_successful_etag_response_is_cached() -> None:
    cache = ResponseCache()
    request = Request("GET", "https://service.test/items", {"Accept": "text/plain"})
    client = CachingClient(
        StaticTransport(Response(200, b"first", {"ETag": '"v1"'})), cache
    )

    assert client.fetch(request).body == b"first"
    assert cache.get(request) == CacheEntry(body=b"first", etag='"v1"')


def test_cache_identity_separates_accept_representations() -> None:
    cache = ResponseCache()
    json_request = Request("GET", "https://service.test/items", {"Accept": "application/json"})
    text_request = Request("GET", "https://service.test/items", {"Accept": "text/plain"})
    cache.put(json_request, CacheEntry(b"{}", '"json"'))

    assert cache.get(text_request) is None
