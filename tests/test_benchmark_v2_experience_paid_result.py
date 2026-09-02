import csv
import json
from pathlib import Path

from evodev.evaluation.experience_experiment import assert_controlled_conditions
from evodev.evaluation.models import ExperimentManifest

RESULT_ROOT = Path("experiments/benchmark-v2-experience-validation-paid-v1")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(arm: str) -> list[dict[str, str]]:
    with (RESULT_ROOT / arm / "summary.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_paid_validation_arms_are_controlled_and_complete() -> None:
    baseline = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "baseline/manifest.json").read_text(encoding="utf-8")
    )
    relevant = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "relevant/manifest.json").read_text(encoding="utf-8")
    )

    assert_controlled_conditions(baseline, relevant)
    assert baseline.benchmark_splits == ["validation"]
    assert baseline.experience_mode == "disabled"
    assert relevant.experience_mode == "relevant"
    assert relevant.experience_version == "experience-v003"
    assert relevant.experience_hash == (
        "53f8ce05c569b94f2969aacff64c43a799b19adec52cdad07a1f59611f1006e9"
    )
    assert len(_rows("baseline")) == len(_rows("relevant")) == 10


def test_paid_validation_summaries_match_every_frozen_row() -> None:
    for arm in ("baseline", "relevant"):
        rows = _rows(arm)
        summary = _json(RESULT_ROOT / arm / "summary.json")

        assert summary["total_attempts"] == len(rows)
        assert summary["valid_evaluated_attempts"] == sum(
            row["valid_evaluation"] == "True" for row in rows
        )
        assert summary["resolved_attempts"] == sum(row["resolved"] == "True" for row in rows)
        assert summary["average_react_steps"] == sum(int(row["react_steps"]) for row in rows) / len(
            rows
        )
        assert summary["average_tokens"] == sum(int(row["tokens"]) for row in rows) / len(rows)


def test_paid_validation_comparison_rejects_an_experience_uplift_claim() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")
    metrics = _json(RESULT_ROOT / "relevant/experience_metrics.json")
    baseline = {row["agent_run_id"]: row for row in _rows("baseline")}
    relevant = {row["agent_run_id"]: row for row in _rows("relevant")}
    discordant = [
        run_id
        for run_id in baseline
        if baseline[run_id]["resolved"] != relevant[run_id]["resolved"]
    ]

    assert comparison["controlled_conditions_verified"] is True
    assert comparison["selective_reruns_performed"] is False
    assert comparison["total_paid_calls"] == 20
    assert comparison["arms"]["baseline"]["resolved"] == 4
    assert comparison["arms"]["relevant"]["resolved"] == 3
    assert discordant == ["run_task_110_r01"]
    assert comparison["paired_outcomes"]["experience_hit_pairs"] == {
        "pairs": 8,
        "baseline_resolved": 2,
        "relevant_resolved": 2,
        "discordant_pairs": 0,
    }
    assert metrics["retrieval_hits"] == 8
    assert metrics["utilized_retrievals"] == 0
    assert comparison["interpretation"]["resolution_uplift_demonstrated"] is False
    assert (
        comparison["interpretation"]["resolution_degradation_attributable_to_experience"] is False
    )
