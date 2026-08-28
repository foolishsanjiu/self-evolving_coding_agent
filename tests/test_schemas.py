from pathlib import Path

import pytest
from pydantic import ValidationError

from evodev.llm import ModelTurn
from evodev.schemas import TaskSpec


def test_task_spec_accepts_valid_task() -> None:
    task = TaskSpec(
        task_id="fixture-001",
        instruction="Inspect the repository.",
        workspace_path=Path("workspace"),
    )

    assert task.task_id == "fixture-001"
    assert task.metadata == {}


def test_task_spec_rejects_empty_instruction() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(task_id="fixture-001", instruction="", workspace_path=Path("workspace"))


def test_model_turn_rejects_negative_usage() -> None:
    with pytest.raises(ValidationError):
        ModelTurn(input_tokens=-1)
