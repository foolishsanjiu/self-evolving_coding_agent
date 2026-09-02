from typing import Protocol

from http_cache.cache import ResponseCache
from http_cache.models import CacheEntry, Request, Response


class Transport(Protocol):
    def send(self, request: Request) -> Response: ...


class CachingClient:
    def __init__(self, transport: Transport, cache: ResponseCache) -> None:
        self.transport = transport
        self.cache = cache

    def fetch(self, request: Request) -> Response:
        response = self.transport.send(request)
        etag = response.headers.get("ETag")
        if response.status_code == 200 and etag:
            self.cache.put(request, CacheEntry(body=response.body, etag=etag))
        return response
