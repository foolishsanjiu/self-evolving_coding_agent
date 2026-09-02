import pytest
from checkpoints import Ack, CheckpointState, CheckpointStore, acknowledge


def test_duplicate_pending_ack_is_idempotent() -> None:
    store = CheckpointStore(
        CheckpointState("orders", checkpoint=5, pending=frozenset({7}))
    )

    result = acknowledge(store, Ack("orders", 7))

    assert result == CheckpointState("orders", checkpoint=5, pending=frozenset({7}))


def test_cross_stream_ack_is_rejected_without_state_change() -> None:
    initial = CheckpointState("orders", checkpoint=5)
    store = CheckpointStore(initial)

    with pytest.raises(ValueError, match="another stream"):
        acknowledge(store, Ack("payments", 6))
    assert store.load() is initial


def test_persistence_failure_keeps_checkpoint_and_pending_state_atomic() -> None:
    initial = CheckpointState("orders", checkpoint=5, pending=frozenset({7}))
    store = CheckpointStore(initial)
    store.fail_next_save = True

    with pytest.raises(OSError, match="persistence failed"):
        acknowledge(store, Ack("orders", 6))
    assert store.load() is initial
