from checkpoints.models import CheckpointState


class CheckpointStore:
    def __init__(self, state: CheckpointState) -> None:
        self.state = state
        self.fail_next_save = False

    def load(self) -> CheckpointState:
        return self.state

    def save(self, state: CheckpointState) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise OSError("checkpoint persistence failed")
        self.state = state
