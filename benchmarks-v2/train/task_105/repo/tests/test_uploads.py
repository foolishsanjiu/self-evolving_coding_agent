from uploads.models import Chunk
from uploads.store import ChunkStore


def test_store_keeps_uploads_isolated() -> None:
    store = ChunkStore()
    store.put(Chunk("left", 0, 2, b"a"))
    store.put(Chunk("right", 0, 1, b"b"))

    assert store.chunks_for("left") == {0: b"a"}
    assert store.chunks_for("right") == {0: b"b"}


def test_store_returns_a_copy_of_chunk_state() -> None:
    store = ChunkStore()
    store.put(Chunk("upload", 0, 1, b"data"))

    snapshot = store.chunks_for("upload")
    snapshot[0] = b"changed"

    assert store.chunk_at("upload", 0) == b"data"
