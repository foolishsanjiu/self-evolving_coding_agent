class ChunkConflictError(ValueError):
    """Raised when one upload receives incompatible chunk metadata or content."""


class IncompleteUploadError(RuntimeError):
    """Raised when assembly is requested before every chunk exists."""
