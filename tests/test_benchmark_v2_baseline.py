import csv
import json
from collections import defaultdict
from pathlib import Path

RESULT_ROOT = Path("experiments/benchmark-v2-train-baseline-v1")
EVIDENCE_ROOT = Path("evolution/benchmark-v2")


def _manifest() -> dict:
    return json.loads((RESULT_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _summary() -> dict:
    return json.loads((RESULT_ROOT / "summary.json").read_text(encoding="utf-8"))


def _rows() -> list[dict[str, str]]:
    with (RESULT_ROOT / "summary.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_formal_v2_baseline_manifest_is_train_only_and_complete() -> None:
    manifest = _manifest()
    expected_tasks = [f"task_{number}" for number in range(101, 109)]
    expected_runs = [
        f"run_{task_id}_r{repetition:02d}"
        for repetition in range(1, 3)
        for task_id in expected_tasks
    ]

    assert manifest["git_commit"] == "e02b7ece0d0494cf89b42b975a1f601395ca28f7"
    assert manifest["benchmark"]["manifest_hash"] == (
        "c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6"
    )
    assert manifest["benchmark"]["splits"] == ["train"]
    assert manifest["benchmark"]["task_ids"] == expected_tasks
    assert manifest["repetitions_per_task"] == 2
    assert manifest["paid_agent_calls"] == 16
    assert manifest["selective_reruns"] is False
    assert manifest["run_ids"] == expected_runs


def test_formal_v2_baseline_summary_matches_per_run_evidence() -> None:
    summary = _summary()
    rows = _rows()

    assert len(rows) == len({row["run_id"] for row in rows}) == 16
    assert all(row["valid_evaluation"] == "true" for row in rows)
    assert sum(row["resolved"] == "true" for row in rows) == 6
    assert sum(int(row["input_tokens"]) for row in rows) == 2_289_513
    assert sum(int(row["output_tokens"]) for row in rows) == 225_762
    assert all(
        int(row["input_tokens"]) + int(row["output_tokens"])
        == int(row["total_tokens"])
        for row in rows
    )
    assert summary["total_attempts"] == summary["valid_evaluated_attempts"] == 16
    assert summary["resolved_attempts"] == 6
    assert summary["resolution_rate"] == 0.375
    assert summary["token_usage"]["total_tokens"] == 2_515_275
    assert summary["token_usage"]["peak_all_cache_miss_estimate_usd"] < 2.0


def test_formal_v2_baseline_repetitions_have_stable_resolution_outcomes() -> None:
    outcomes: dict[str, list[bool]] = defaultdict(list)
    for row in _rows():
        outcomes[row["task_id"]].append(row["resolved"] == "true")

    assert outcomes == {
        "task_101": [True, True],
        "task_102": [True, True],
        "task_103": [False, False],
        "task_104": [True, True],
        "task_105": [False, False],
        "task_106": [False, False],
        "task_107": [False, False],
        "task_108": [False, False],
    }


def test_v2_failure_patterns_account_for_ineligible_failures_explicitly() -> None:
    report = json.loads(
        (EVIDENCE_ROOT / "failure-patterns-baseline-v2-train-v1.json").read_text(
            encoding="utf-8"
        )
    )
    patterns = {item["failure_type"]: item for item in report["patterns"]}

    assert report["split"] == "train"
    assert report["total_failed_runs"] == 10
    assert report["eligible_failed_runs"] == 9
    assert {name: item["failed_runs"] for name, item in patterns.items()} == {
        "AGENT_MAX_STEPS": 1,
        "REGRESSION_FAILED": 4,
        "TARGET_TEST_FAILED": 4,
    }
    assert report["excluded_failures"] == [
        {
            "run_id": "exp-baseline-v2-train-v1/run_task_108_r01",
            "failure_type": "SYNTAX_ERROR",
            "reason": "failure_not_reflection_eligible",
        }
    ]


def test_v2_failure_audit_matches_all_frozen_failed_runs() -> None:
    audit = json.loads(
        (EVIDENCE_ROOT / "failure-audit-v1.json").read_text(encoding="utf-8")
    )
    frozen_failures = {
        row["run_id"] for row in _rows() if row["resolved"] == "false"
    }
    diagnostics = audit["diagnostics"]

    assert audit["source"]["benchmark_splits"] == ["train"]
    assert audit["accounting"]["failed_runs"] == len(diagnostics) == 10
    assert {item["run_id"] for item in diagnostics} == frozen_failures
    assert sum(item["reflection_eligible"] for item in diagnostics) == 9
    assert audit["accounting"]["searched_before_edit"] == 10
    assert audit["accounting"]["inspected_tests_before_edit"] == 10
    assert sum(audit["primary_categories"].values()) == 10
