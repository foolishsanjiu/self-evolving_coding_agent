import json
from pathlib import Path

import yaml

from evodev.experience import load_snapshot

RESULT_ROOT = Path("experiments/benchmark-v2-experience-train-holdout-paid-v1")
CONFIG = Path(
    "configs/experiments/benchmark-v2-experience-train-holdout-paid-v1.yaml"
)


def test_train_holdout_plan_freezes_the_only_cross_task_hit() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    preflight = json.loads((RESULT_ROOT / "preflight.json").read_text(encoding="utf-8"))

    assert config["status"] == "authorized_before_execution"
    assert config["scientific_scope"]["selected_tasks"] == ["task_101"]
    assert config["scientific_scope"]["repetitions_per_arm"] == 2
    assert config["scientific_scope"]["selective_reruns_allowed"] is False
    assert config["execution"]["total_paid_calls"] == 4
    assert config["authorization"]["maximum_projected_cost_usd"] == 0.5
    assert preflight["decision"] == "ready_for_paid_execution"
    assert preflight["runs"] == ["run_task_101_r01", "run_task_101_r02"]
    assert preflight["total_paid_calls"] == 4
    assert preflight["selective_reruns_allowed"] is False


def test_train_holdout_plan_binds_both_frozen_snapshots_and_consumers() -> None:
    preflight = json.loads((RESULT_ROOT / "preflight.json").read_text(encoding="utf-8"))
    v003 = load_snapshot(Path(preflight["arms"]["v003"]["snapshot"]))
    v004 = load_snapshot(Path(preflight["arms"]["v004"]["snapshot"]))

    assert preflight["arms"]["v003"]["experience_hash"] == v003.content_hash
    assert preflight["arms"]["v003"]["consumer"] == "legacy-v1"
    assert preflight["arms"]["v004"]["experience_hash"] == v004.content_hash
    assert preflight["arms"]["v004"]["consumer"] == "execution-contract-v1"
    assert all(item.execution_contract is None for item in v003.experiences)
    assert all(item.execution_contract is not None for item in v004.experiences)


def test_train_holdout_commands_keep_split_task_and_paid_gate_explicit() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    for command in (
        config["execution"]["v003_command"],
        config["execution"]["v004_command"],
    ):
        assert "--split train" in command
        assert "--task-id task_101" in command
        assert "--repetitions 2" in command
        assert "--confirm-paid" in command
    assert config["boundaries"] == {
        "same_task_experience_sources_excluded": True,
        "validation_split_accessed": False,
        "test_split_accessed": False,
        "gold_patch_exposed_to_agent": False,
        "hidden_tests_exposed_to_agent": False,
        "hidden_tests_used_only_by_independent_evaluator": True,
    }
