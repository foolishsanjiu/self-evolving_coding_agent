from dataclasses import dataclass


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes
