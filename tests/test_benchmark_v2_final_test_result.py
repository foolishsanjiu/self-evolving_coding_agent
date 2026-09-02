import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from evodev.evaluation.experience_experiment import assert_controlled_conditions
from evodev.evaluation.models import ExperimentManifest
from evodev.experience.guardrails import analyze_guardrail_trace

RESULT_ROOT = Path("experiments/benchmark-v2-final-test-v1")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(arm: str) -> list[dict[str, str]]:
    with (RESULT_ROOT / arm / "summary.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_final_test_result_freezes_all_attempts_and_rejects_uplift() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")

    assert comparison["execution_contract_commit"] == "dea968e"
    assert comparison["selective_reruns"] == 0
    assert comparison["arms"]["baseline"]["valid_attempts"] == 10
    assert comparison["arms"]["candidate"]["valid_attempts"] == 10
    assert comparison["arms"]["baseline"]["resolved"] == 3
    assert comparison["arms"]["candidate"]["resolved"] == 3
    decision = comparison["decision"]
    assert decision["test_closed"] is True
    assert decision["post_test_tuning_allowed"] is False
    assert decision["performance_uplift_accepted"] is False
    assert decision["efficiency_uplift_accepted"] is False
    assert "no evidence" in decision["conclusion"]


def test_final_test_manifests_change_only_registered_experience_fields() -> None:
    baseline = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "baseline/manifest.json").read_text(encoding="utf-8")
    )
    candidate = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "candidate/manifest.json").read_text(encoding="utf-8")
    )

    assert_controlled_conditions(baseline, candidate)
    assert baseline.benchmark_splits == candidate.benchmark_splits == ["test"]
    assert baseline.experience_mode == "disabled"
    assert candidate.experience_version == "experience-v005"
    assert candidate.experience_consumer == "execution-contract-v2"


def test_final_test_pairwise_outcomes_recompute_from_public_csv() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")
    baseline = {(row["task_id"], row["agent_run_id"]): row for row in _rows("baseline")}
    candidate = {(row["task_id"], row["agent_run_id"]): row for row in _rows("candidate")}

    assert baseline.keys() == candidate.keys()
    outcomes = Counter()
    per_task = Counter()
    for key in baseline:
        baseline_resolved = baseline[key]["resolved"] == "True"
        candidate_resolved = candidate[key]["resolved"] == "True"
        if baseline_resolved and not candidate_resolved:
            outcomes["baseline_wins"] += 1
        elif candidate_resolved and not baseline_resolved:
            outcomes["candidate_wins"] += 1
        else:
            outcomes["ties"] += 1
        per_task[(key[0], "baseline")] += baseline_resolved
        per_task[(key[0], "candidate")] += candidate_resolved

    paired = comparison["paired_outcomes"]
    assert outcomes == Counter(baseline_wins=2, candidate_wins=2, ties=6)
    assert paired["baseline_wins"] == outcomes["baseline_wins"]
    assert paired["candidate_wins"] == outcomes["candidate_wins"]
    assert paired["ties"] == outcomes["ties"]
    assert paired["discordant_pairs"] == 4
    assert paired["exact_mcnemar_two_sided_p"] == 1.0
    for item in paired["per_task"]:
        task_id = item["task_id"]
        assert item["baseline_resolved"] == per_task[(task_id, "baseline")]
        assert item["candidate_resolved"] == per_task[(task_id, "candidate")]


def test_final_test_cost_experience_and_behavior_are_consistent() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")
    metrics = _json(RESULT_ROOT / "candidate/experience_metrics.json")
    behavior = _json(RESULT_ROOT / "guardrail-behavior.json")

    cost = comparison["cost"]
    estimated = (
        cost["total_input_tokens"] * 0.22 + cost["total_output_tokens"] * 0.66
    ) / 1_000_000
    assert cost["estimated_total_usd"] == pytest.approx(estimated, abs=0.0001)
    assert cost["estimated_total_usd"] < cost["authorized_ceiling_usd"]
    assert metrics["retrieval_hits"] == metrics["adherent_retrievals"] == 10
    assert metrics["utilized_retrievals"] == 0
    assert behavior["baseline"]["executed_uninspected_patch_retries"] == 22
    assert behavior["candidate"]["blocked_uninspected_patch_retries"] == 2
    assert behavior["candidate"]["verification_window_blocks"] == 8


def test_final_test_evidence_hashes_match_committed_files() -> None:
    evidence = _json(RESULT_ROOT / "evidence-manifest.json")
    files = {
        "execution_contract": Path("configs/experiments/benchmark-v2-final-test-v1.yaml"),
        "preflight": RESULT_ROOT / "preflight.json",
        "benchmark_manifest": Path("benchmarks-v2/manifest.json"),
        "experience_v005_file": Path("experiences/experience-v005.json"),
        "baseline_manifest": RESULT_ROOT / "baseline/manifest.json",
        "baseline_summary_json": RESULT_ROOT / "baseline/summary.json",
        "baseline_summary_csv": RESULT_ROOT / "baseline/summary.csv",
        "candidate_manifest": RESULT_ROOT / "candidate/manifest.json",
        "candidate_summary_json": RESULT_ROOT / "candidate/summary.json",
        "candidate_summary_csv": RESULT_ROOT / "candidate/summary.csv",
        "candidate_experience_metrics": RESULT_ROOT / "candidate/experience_metrics.json",
        "comparison": RESULT_ROOT / "comparison.json",
        "guardrail_behavior": RESULT_ROOT / "guardrail-behavior.json",
    }
    assert {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()
    } == evidence["sha256"]


def test_local_final_test_raw_evidence_recomputes_when_present() -> None:
    evidence = _json(RESULT_ROOT / "evidence-manifest.json")
    comparison = _json(RESULT_ROOT / "comparison.json")
    arm_ids = {
        "baseline": "exp-baseline-v2-test-final-v1",
        "candidate": "exp-experience-v005-test-final-v1",
    }
    if not all(Path("runs", arm_id).is_dir() for arm_id in arm_ids.values()):
        pytest.skip("Raw final Test evidence is intentionally gitignored")

    behavior = _json(RESULT_ROOT / "guardrail-behavior.json")
    expected_metrics = {
        "patch_attempts",
        "patch_failures",
        "uninspected_patch_retry_attempts",
        "blocked_uninspected_patch_retries",
        "executed_uninspected_patch_retries",
        "verification_window_blocks",
        "final_answer_blocks",
        "total_contract_blocks",
        "test_calls",
        "test_executions",
    }
    for arm, arm_id in arm_ids.items():
        run_root = Path("runs", arm_id)
        evaluation_root = Path("evaluation_runs", arm_id, "instances")
        files = list(run_root.glob("*/events.jsonl"))
        files += list(run_root.glob("*/final.patch"))
        files += list(evaluation_root.glob("**/report.json"))
        if arm == "candidate":
            files += list(run_root.glob("*/retrieval.json"))
        files = sorted(files, key=lambda path: path.as_posix())
        records = [
            f"{path.as_posix()}\0{hashlib.sha256(path.read_bytes()).hexdigest()}"
            for path in files
        ]
        raw = evidence["raw_local_evidence"][arm]
        assert len(files) == raw["file_count"]
        assert hashlib.sha256("\n".join(records).encode()).hexdigest() == raw[
            "tree_sha256"
        ]

        measured = Counter()
        verified_runs = 0
        input_tokens = 0
        output_tokens = 0
        for events_path in sorted(run_root.glob("*/events.jsonl")):
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            result = analyze_guardrail_trace(events)
            for metric in expected_metrics:
                measured[metric] += int(result[metric])
            verified_runs += int(result["last_successful_edit_verified"])
            for event in events:
                if event["type"] == "MODEL_TURN":
                    input_tokens += int(event["data"]["input_tokens"])
                    output_tokens += int(event["data"]["output_tokens"])
        for metric in expected_metrics:
            assert measured[metric] == behavior[arm][metric]
        assert verified_runs == behavior[arm]["last_successful_edit_verified_runs"]
        assert input_tokens == comparison["arms"][arm]["input_tokens"]
        assert output_tokens == comparison["arms"][arm]["output_tokens"]
