import pytest
from uploads import Chunk, ChunkConflictError, IncompleteUploadError, UploadAssembler


@pytest.mark.parametrize(
    "chunk",
    [
        Chunk("bad", 0, 0, b"x"),
        Chunk("bad", -1, 2, b"x"),
        Chunk("bad", 2, 2, b"x"),
    ],
)
def test_invalid_chunk_bounds_are_rejected_without_mutating_state(chunk: Chunk) -> None:
    assembler = UploadAssembler()

    with pytest.raises(ChunkConflictError):
        assembler.add_chunk(chunk)
    assert assembler.store.chunks_for("bad") == {}


def test_incomplete_and_independent_uploads_remain_separate() -> None:
    assembler = UploadAssembler()
    assembler.add_chunk(Chunk("first", 0, 2, b"a"))
    completed = assembler.add_chunk(Chunk("second", 0, 1, b"done"))

    assert completed == b"done"
    with pytest.raises(IncompleteUploadError):
        assembler.assemble("first")
    assert assembler.assemble("second") == b"done"
