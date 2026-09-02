from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ack:
    stream_id: str
    sequence: int


@dataclass(frozen=True)
class CheckpointState:
    stream_id: str
    checkpoint: int = 0
    pending: frozenset[int] = field(default_factory=frozenset)
