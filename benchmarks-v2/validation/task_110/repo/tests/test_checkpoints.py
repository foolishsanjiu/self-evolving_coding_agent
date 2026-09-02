from checkpoints import Ack, CheckpointState, CheckpointStore, acknowledge


def test_late_acknowledgement_is_idempotent() -> None:
    initial = CheckpointState("orders", checkpoint=5)
    store = CheckpointStore(initial)

    result = acknowledge(store, Ack("orders", 4))

    assert result is initial
    assert store.load() is initial


def test_store_round_trips_an_immutable_state() -> None:
    state = CheckpointState("events", checkpoint=3, pending=frozenset({5}))

    assert CheckpointStore(state).load() == state
