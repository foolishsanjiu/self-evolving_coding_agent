from uploads.models import Chunk


class ChunkStore:
    def __init__(self) -> None:
        self._chunks: dict[str, dict[int, bytes]] = {}
        self._totals: dict[str, int] = {}

    def put(self, chunk: Chunk) -> None:
        self._totals.setdefault(chunk.upload_id, chunk.total)
        self._chunks.setdefault(chunk.upload_id, {})[chunk.index] = chunk.data

    def total_for(self, upload_id: str) -> int | None:
        return self._totals.get(upload_id)

    def chunk_at(self, upload_id: str, index: int) -> bytes | None:
        return self._chunks.get(upload_id, {}).get(index)

    def chunks_for(self, upload_id: str) -> dict[int, bytes]:
        return dict(self._chunks.get(upload_id, {}))
