from uploads.errors import IncompleteUploadError
from uploads.models import Chunk
from uploads.store import ChunkStore


class UploadAssembler:
    def __init__(self, store: ChunkStore | None = None) -> None:
        self.store = store or ChunkStore()

    def add_chunk(self, chunk: Chunk) -> bytes | None:
        self.store.put(chunk)
        return None

    def is_complete(self, upload_id: str) -> bool:
        return False

    def assemble(self, upload_id: str) -> bytes:
        raise IncompleteUploadError(upload_id)
