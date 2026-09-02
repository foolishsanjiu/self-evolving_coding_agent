import json
from pathlib import Path

import yaml

from evodev.experience import load_snapshot

RESULT_ROOT = Path("experiments/benchmark-v2-experience-guardrails-paid-v1")
CONFIG = Path(
    "configs/experiments/benchmark-v2-experience-guardrails-paid-v1.yaml"
)


def test_guardrail_paid_plan_freezes_only_cross_task_hit_and_four_calls() -> None:
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


def test_guardrail_paid_plan_binds_snapshots_consumers_and_runtime_change() -> None:
    preflight = json.loads((RESULT_ROOT / "preflight.json").read_text(encoding="utf-8"))
    v004 = load_snapshot(Path(preflight["arms"]["v004"]["snapshot"]))
    v005 = load_snapshot(Path(preflight["arms"]["v005"]["snapshot"]))

    assert preflight["arms"]["v004"]["experience_hash"] == v004.content_hash
    assert preflight["arms"]["v004"]["consumer"] == "execution-contract-v1"
    assert preflight["arms"]["v005"]["experience_hash"] == v005.content_hash
    assert preflight["arms"]["v005"]["consumer"] == "execution-contract-v2"
    assert all(item.execution_contract.guardrails is None for item in v004.experiences)
    assert all(item.execution_contract.guardrails is not None for item in v005.experiences)


def test_guardrail_paid_commands_and_data_boundaries_are_explicit() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    for command in (
        config["execution"]["v004_command"],
        config["execution"]["v005_command"],
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
