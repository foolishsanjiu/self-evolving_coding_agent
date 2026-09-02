from http_cache.models import CacheEntry, Request

CacheKey = tuple[str, str, str]


def request_key(request: Request) -> CacheKey:
    return (request.method.upper(), request.url, request.headers.get("Accept", ""))


class ResponseCache:
    def __init__(self) -> None:
        self._entries: dict[CacheKey, CacheEntry] = {}

    def get(self, request: Request) -> CacheEntry | None:
        return self._entries.get(request_key(request))

    def put(self, request: Request, entry: CacheEntry) -> None:
        self._entries[request_key(request)] = entry
