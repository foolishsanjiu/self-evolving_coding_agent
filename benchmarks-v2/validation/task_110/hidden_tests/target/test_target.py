from checkpoints import Ack, CheckpointState, CheckpointStore, acknowledge


def test_gap_stays_pending_until_contiguous_ack_arrives() -> None:
    store = CheckpointStore(CheckpointState("orders", checkpoint=10))

    first = acknowledge(store, Ack("orders", 12))
    second = acknowledge(store, Ack("orders", 11))

    assert first.checkpoint == 10
    assert first.pending == frozenset({12})
    assert second.checkpoint == 12
    assert second.pending == frozenset()


def test_multiple_out_of_order_acks_collapse_across_the_entire_contiguous_range() -> None:
    store = CheckpointStore(CheckpointState("events", checkpoint=20))
    acknowledge(store, Ack("events", 23))
    acknowledge(store, Ack("events", 22))

    result = acknowledge(store, Ack("events", 21))

    assert result.checkpoint == 23
    assert result.pending == frozenset()
