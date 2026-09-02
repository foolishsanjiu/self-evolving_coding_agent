from dataclasses import dataclass


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    etag: str
