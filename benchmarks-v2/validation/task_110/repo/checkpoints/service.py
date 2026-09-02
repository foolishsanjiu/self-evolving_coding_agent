from checkpoints.models import Ack, CheckpointState
from checkpoints.store import CheckpointStore


def acknowledge(store: CheckpointStore, ack: Ack) -> CheckpointState:
    state = store.load()
    if ack.stream_id != state.stream_id:
        raise ValueError("acknowledgement belongs to another stream")
    if ack.sequence <= state.checkpoint:
        return state
    updated = CheckpointState(
        stream_id=state.stream_id,
        checkpoint=ack.sequence,
        pending=frozenset(),
    )
    store.save(updated)
    return updated
