import csv
import hashlib
import json
from pathlib import Path

from evodev.evaluation.models import ExperimentManifest, ExperimentSummary
from evodev.experience import ExperienceMetrics, analyze_guardrail_trace

RESULT_ROOT = Path("experiments/benchmark-v2-experience-guardrails-paid-v1")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_guardrail_paid_arms_change_only_frozen_experience_conditions() -> None:
    v004 = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "v004/manifest.json").read_text(encoding="utf-8")
    )
    v005 = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "v005/manifest.json").read_text(encoding="utf-8")
    )
    allowed = {
        "created_at",
        "experiment_id",
        "experiment_version",
        "experience_consumer",
        "experience_hash",
        "experience_version",
    }

    assert v004.model_dump(exclude=allowed) == v005.model_dump(exclude=allowed)
    assert v004.benchmark_splits == v005.benchmark_splits == ["train"]
    assert v004.experience_consumer == "execution-contract-v1"
    assert v005.experience_consumer == "execution-contract-v2"


def test_guardrail_paid_summaries_and_metrics_match_frozen_rows() -> None:
    expected_resolved = {"v004": 1, "v005": 2}
    for arm in ("v004", "v005"):
        summary = ExperimentSummary.model_validate_json(
            (RESULT_ROOT / arm / "summary.json").read_text(encoding="utf-8")
        )
        metrics = ExperienceMetrics.model_validate_json(
            (RESULT_ROOT / arm / "experience_metrics.json").read_text(encoding="utf-8")
        )
        with (RESULT_ROOT / arm / "summary.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))

        assert len(rows) == summary.total_attempts == summary.valid_evaluated_attempts == 2
        assert summary.resolved_attempts == expected_resolved[arm]
        assert sum(row["resolved"] == "True" for row in rows) == expected_resolved[arm]
        assert metrics.retrieval_attempts == metrics.retrieval_hits == 2
        assert metrics.adherent_retrievals == 2
        assert metrics.utilized_retrievals == 0


def test_guardrail_paid_result_demonstrates_enforcement_not_performance_uplift() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")
    behavior = _json(RESULT_ROOT / "guardrail-behavior.json")

    assert comparison["execution_contract_commit"].startswith("3ffe514")
    assert comparison["controlled_conditions_verified"] is True
    assert comparison["selective_reruns_performed"] is False
    assert comparison["total_paid_calls"] == 4
    assert comparison["paired_outcomes"] == {
        "pairs": 2,
        "v004_wins": 0,
        "v005_wins": 1,
        "ties": 1,
        "two_sided_exact_mcnemar_p": 1.0,
        "rows": [
            {
                "run_id": "run_task_101_r01",
                "v004_resolved": False,
                "v005_resolved": True,
            },
            {
                "run_id": "run_task_101_r02",
                "v004_resolved": True,
                "v005_resolved": True,
            },
        ],
    }
    assert behavior["aggregate"]["v004"]["executed_uninspected_patch_retries"] == 9
    assert behavior["aggregate"]["v005"] == {
        "patch_attempts": 11,
        "patch_failures": 4,
        "uninspected_patch_retry_attempts": 2,
        "blocked_uninspected_patch_retries": 2,
        "executed_uninspected_patch_retries": 0,
        "verification_window_blocks": 2,
        "final_answer_blocks": 0,
        "total_contract_blocks": 4,
        "test_calls": 5,
        "test_executions": 5,
        "verified_final_edits": 2,
    }
    assert comparison["interpretation"]["runtime_enforcement_observed"] is True
    assert comparison["interpretation"]["resolution_uplift_demonstrated"] is False
    assert comparison["interpretation"]["efficiency_improvement_demonstrated"] is False
    assert comparison["cost"]["conservative_total_usd"] == 0.1303
    assert comparison["cost"]["conservative_total_usd"] < comparison["cost"][
        "authorization_ceiling_usd"
    ]


def test_local_guardrail_paid_evidence_recomputes_and_matches_hashes_when_present() -> None:
    evidence = _json(RESULT_ROOT / "evidence-manifest.json")
    behavior = _json(RESULT_ROOT / "guardrail-behavior.json")
    experiment_ids = {
        "v004": "exp-experience-v004-train-guardrail-control-v1",
        "v005": "exp-experience-v005-train-guardrail-v1",
    }
    if not (Path("evaluation_runs") / experiment_ids["v004"]).is_dir():
        return

    for arm, experiment in experiment_ids.items():
        evaluation_root = Path("evaluation_runs") / experiment
        for filename, suffix in (
            ("manifest.json", "manifest"),
            ("summary.json", "summary_json"),
            ("summary.csv", "summary_csv"),
            ("experience_metrics.json", "experience_metrics"),
        ):
            assert _sha256(evaluation_root / filename) == evidence["arm_artifacts"][
                f"{arm}_{suffix}"
            ]
        for repetition in (1, 2):
            run_label = f"r{repetition:02d}"
            run_id = f"run_task_101_{run_label}"
            run_root = Path("runs") / experiment / run_id
            for filename, suffix in (
                ("events.jsonl", "events"),
                ("retrieval.json", "retrieval"),
                ("trace_features.json", "trace_features"),
                ("final.patch", "final_patch"),
            ):
                assert _sha256(run_root / filename) == evidence["run_artifacts"][
                    f"{arm}_{run_label}_{suffix}"
                ]
            events = [
                json.loads(line)
                for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
            frozen = behavior["runs"][arm][run_id]
            measured = analyze_guardrail_trace(events)
            for key in (
                "patch_attempts",
                "patch_failures",
                "uninspected_patch_retry_attempts",
                "blocked_uninspected_patch_retries",
                "executed_uninspected_patch_retries",
                "verification_window_blocks",
                "final_answer_blocks",
                "total_contract_blocks",
                "max_consecutive_patch_failures",
                "test_calls",
                "test_executions",
                "last_successful_edit_verified",
                "finish_status",
            ):
                assert measured[key] == frozen[key]
            report = (
                evaluation_root
                / "instances/task_101"
                / f"attempt_{repetition:02d}/report.json"
            )
            assert _sha256(report) == evidence["run_artifacts"][
                f"{arm}_{run_label}_evaluation_report"
            ]
