"""Optional runtime guards derived from structured Experience contracts."""

from pydantic import BaseModel, ConfigDict


class ExecutionGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspect_after_patch_failure: bool = False
    verify_after_last_edit: bool = False

    @property
    def enabled(self) -> bool:
        return self.inspect_after_patch_failure or self.verify_after_last_edit
