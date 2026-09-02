from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    upload_id: str
    index: int
    total: int
    data: bytes
