from pathlib import Path

import pytest
import yaml

from evodev.config import load_settings
from evodev.evaluation.baseline import (
    FixedPolicyBaselineRunner,
    build_baseline_preflight,
    require_baseline_paid_confirmation,
)

PROJECT_ROOT = Path.cwd()
BENCHMARK_ROOT = Path("benchmarks-v2")
PLAN_PATH = Path("configs/experiments/benchmark-v2-train-baseline-v1.yaml")


def _settings():
    settings = load_settings(Path("configs"))
    return settings.model_copy(
        update={
            "model": settings.model.model_copy(update={"model": "deepseek-v4-flash"})
        }
    )


def test_v2_train_baseline_preflight_is_exactly_sixteen_paid_runs() -> None:
    preflight = build_baseline_preflight(
        PROJECT_ROOT,
        _settings(),
        experiment_id="exp-baseline-v2-train-v1",
        repetitions=2,
        benchmark_root=BENCHMARK_ROOT,
        benchmark_splits=("train",),
    )

    assert preflight.benchmark_hash == (
        "c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6"
    )
    assert preflight.benchmark_splits == ["train"]
    assert preflight.task_ids == [f"task_{number}" for number in range(101, 109)]
    assert preflight.repetitions == 2
    assert preflight.expected_agent_runs == len(preflight.runs) == 16
    assert [run.agent_run_id for run in preflight.runs[:8]] == [
        f"run_task_{number}_r01" for number in range(101, 109)
    ]
    assert [run.agent_run_id for run in preflight.runs[8:]] == [
        f"run_task_{number}_r02" for number in range(101, 109)
    ]
    assert preflight.model == "deepseek-v4-flash"
    assert preflight.requires_paid_confirmation is True
    assert preflight.selective_reruns_allowed is False


def test_baseline_runner_filters_tasks_before_paid_execution(tmp_path: Path) -> None:
    runner = FixedPolicyBaselineRunner(
        tmp_path,
        _settings(),
        experiment_id="offline-plan-test",
        repetitions=2,
        benchmark_root=(PROJECT_ROOT / BENCHMARK_ROOT).resolve(),
        benchmark_splits=("train",),
    )

    assert [task.config.task_id for task in runner.tasks] == [
        f"task_{number}" for number in range(101, 109)
    ]
    assert runner.benchmark_splits == ("train",)


@pytest.mark.parametrize("splits", [(), ("train", "train")])
def test_baseline_preflight_rejects_ambiguous_split_selection(splits) -> None:
    with pytest.raises(ValueError, match="split"):
        build_baseline_preflight(
            PROJECT_ROOT,
            _settings(),
            experiment_id="invalid-plan",
            repetitions=1,
            benchmark_root=BENCHMARK_ROOT,
            benchmark_splits=splits,
        )


def test_paid_baseline_requires_explicit_confirmation() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        require_baseline_paid_confirmation(False)

    require_baseline_paid_confirmation(True)


def test_cost_projection_matches_official_rates_and_pilot_usage() -> None:
    plan = yaml.safe_load(PLAN_PATH.read_text(encoding="utf-8"))
    pricing = plan["pricing_snapshot"]["per_million_tokens"]
    projection = plan["projection_for_16_runs"]
    historical = plan["historical_token_basis"]

    assert plan["design"]["expected_paid_agent_runs"] == 16
    assert plan["design"]["validation_access"] == "forbidden"
    assert plan["design"]["test_access"] == "forbidden"
    assert projection["input_tokens"] == historical["input_tokens"] * 2
    assert projection["output_tokens"] == historical["output_tokens"] * 2
    off_peak = (
        projection["input_tokens"] * pricing["off_peak_cache_miss_input"]
        + projection["output_tokens"] * pricing["off_peak_output"]
    ) / 1_000_000
    peak = (
        projection["input_tokens"] * pricing["peak_cache_miss_input"]
        + projection["output_tokens"] * pricing["peak_output"]
    ) / 1_000_000
    assert projection["off_peak_cache_miss_usd"] == pytest.approx(off_peak, abs=0.0001)
    assert projection["peak_cache_miss_usd"] == pytest.approx(peak, abs=0.0001)
    assert projection["double_token_peak_usd"] == pytest.approx(peak * 2, abs=0.0001)
    assert projection["authorization_ceiling_usd"] == 2.0
