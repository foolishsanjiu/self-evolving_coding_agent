import pytest
from uploads import Chunk, ChunkConflictError, UploadAssembler


def test_out_of_order_chunks_complete_exactly_once_all_are_present() -> None:
    assembler = UploadAssembler()

    assert assembler.add_chunk(Chunk("video", 2, 3, b"C")) is None
    assert assembler.add_chunk(Chunk("video", 0, 3, b"A")) is None
    assert assembler.add_chunk(Chunk("video", 1, 3, b"B")) == b"ABC"
    assert assembler.is_complete("video") is True
    assert assembler.assemble("video") == b"ABC"


def test_duplicate_chunks_are_idempotent_but_conflicts_are_rejected() -> None:
    assembler = UploadAssembler()
    chunk = Chunk("archive", 0, 2, b"left")

    assert assembler.add_chunk(chunk) is None
    assert assembler.add_chunk(chunk) is None
    with pytest.raises(ChunkConflictError):
        assembler.add_chunk(Chunk("archive", 0, 2, b"other"))
    with pytest.raises(ChunkConflictError):
        assembler.add_chunk(Chunk("archive", 1, 3, b"right"))
