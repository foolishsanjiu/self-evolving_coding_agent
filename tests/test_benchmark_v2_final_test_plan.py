import json
import sys
from pathlib import Path

import pytest
import yaml

from evodev.config import load_settings
from evodev.evaluation import experience_experiment
from evodev.evaluation.experience_experiment import (
    audit_retrieval,
    build_experience_arm_preflight,
)

PROJECT_ROOT = Path.cwd()
BENCHMARK_ROOT = Path("benchmarks-v2")
CONFIG = Path("configs/experiments/benchmark-v2-final-test-v1.yaml")
PREFLIGHT = Path("experiments/benchmark-v2-final-test-v1/preflight.json")


def _settings():
    settings = load_settings(Path("configs"))
    return settings.model_copy(
        update={
            "model": settings.model.model_copy(update={"model": "deepseek-v4-flash"})
        }
    )


def test_final_test_plan_freezes_all_test_tasks_and_twenty_calls() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))

    assert config["status"] == "awaiting_paid_authorization"
    assert config["design"]["split"] == "test"
    assert config["design"]["tasks"] == [f"task_{number}" for number in range(114, 119)]
    assert config["design"]["repetitions_per_arm"] == 2
    assert config["design"]["selective_reruns_allowed"] is False
    assert config["execution"]["baseline_calls"] == 10
    assert config["execution"]["candidate_calls"] == 10
    assert config["execution"]["total_paid_calls"] == 20
    assert preflight["decision"] == "awaiting_explicit_paid_authorization"
    assert preflight["total_paid_calls"] == 20
    assert preflight["test_result_is_terminal"] is True


def test_final_test_candidate_preflight_supports_test_without_baseline_result() -> None:
    preflight = build_experience_arm_preflight(
        PROJECT_ROOT,
        _settings(),
        PROJECT_ROOT / "experiences/experience-v005.json",
        experiment_id="exp-experience-v005-test-final-v1",
        mode="relevant",
        repetitions=2,
        benchmark_root=BENCHMARK_ROOT,
        baseline_manifest_path=Path(
            "evaluation_runs/exp-baseline-v2-test-final-v1/manifest.json"
        ),
        split="test",
    )

    assert preflight["benchmark_splits"] == ["test"]
    assert preflight["task_ids"] == [f"task_{number}" for number in range(114, 119)]
    assert preflight["expected_paid_calls"] == 10
    assert preflight["experience_version"] == "experience-v005"
    assert preflight["experience_consumer"] == "execution-contract-v2"
    assert preflight["baseline_manifest_ready"] is False


def test_experience_cli_test_plan_is_safe_and_lists_ten_runs(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evodev-experience-experiment",
            "--project-root",
            ".",
            "--benchmark-root",
            "benchmarks-v2",
            "--snapshot",
            "experiences/experience-v005.json",
            "--mode",
            "relevant",
            "--experiment-id",
            "exp-experience-v005-test-final-v1",
            "--repetitions",
            "2",
            "--split",
            "test",
            "--baseline-manifest",
            "evaluation_runs/exp-baseline-v2-test-final-v1/manifest.json",
            "--plan",
        ],
    )

    experience_experiment.main()

    plan = json.loads(capsys.readouterr().out)
    assert plan["benchmark_splits"] == ["test"]
    assert plan["expected_paid_calls"] == 10
    assert plan["requires_paid_confirmation"] is True


def test_retrieval_audit_cannot_inspect_test_split() -> None:
    with pytest.raises(ValueError, match="train and validation"):
        audit_retrieval(
            PROJECT_ROOT,
            PROJECT_ROOT / "experiences/experience-v005.json",
            BENCHMARK_ROOT,
            split="test",  # type: ignore[arg-type]
        )


def test_final_test_commands_and_terminal_boundaries_are_explicit() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    for command in (
        config["execution"]["baseline_command"],
        config["execution"]["candidate_command"],
    ):
        assert "--split test" in command
        assert "--repetitions 2" in command
        assert "--confirm-paid" in command
    assert config["boundaries"] == {
        "test_tasks_selected_after_outcomes": False,
        "test_public_metadata_used_for_inventory_only": True,
        "test_agent_execution_started": False,
        "selective_reruns_allowed": False,
        "post_test_tuning_allowed": False,
        "gold_patch_exposed_to_agent": False,
        "hidden_tests_exposed_to_agent": False,
        "hidden_tests_used_only_by_independent_evaluator": True,
    }


def test_final_test_cost_projection_and_ceiling_are_consistent() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pricing = config["pricing_preflight"]["per_million_tokens"]
    projection = config["pricing_preflight"]["projection_for_20_calls"]

    off_peak = (
        projection["input_tokens"] * pricing["off_peak_cache_miss_input"]
        + projection["output_tokens"] * pricing["off_peak_output"]
    ) / 1_000_000
    peak = (
        projection["input_tokens"] * pricing["peak_cache_miss_input"]
        + projection["output_tokens"] * pricing["peak_output"]
    ) / 1_000_000
    assert projection["off_peak_all_cache_miss_usd"] == pytest.approx(off_peak, abs=0.0001)
    assert projection["peak_all_cache_miss_usd"] == pytest.approx(peak, abs=0.0001)
    assert projection["double_token_peak_usd"] == pytest.approx(peak * 2, abs=0.0001)
    assert config["authorization"]["maximum_projected_cost_usd"] >= projection[
        "double_token_peak_usd"
    ]
