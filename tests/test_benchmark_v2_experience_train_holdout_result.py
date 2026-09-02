import csv
import hashlib
import json
from pathlib import Path

from evodev.evaluation.models import ExperimentManifest, ExperimentSummary
from evodev.experience import ExperienceMetrics

RESULT_ROOT = Path("experiments/benchmark-v2-experience-train-holdout-paid-v1")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_train_holdout_arms_change_only_frozen_experience_conditions() -> None:
    v003 = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "v003/manifest.json").read_text(encoding="utf-8")
    )
    v004 = ExperimentManifest.model_validate_json(
        (RESULT_ROOT / "v004/manifest.json").read_text(encoding="utf-8")
    )
    allowed = {
        "created_at",
        "experiment_id",
        "experiment_version",
        "experience_consumer",
        "experience_hash",
        "experience_version",
    }

    assert v003.model_dump(exclude=allowed) == v004.model_dump(exclude=allowed)
    assert v003.benchmark_splits == v004.benchmark_splits == ["train"]
    assert v003.experience_consumer == "legacy-v1"
    assert v004.experience_consumer == "execution-contract-v1"


def test_train_holdout_summaries_and_metrics_match_frozen_rows() -> None:
    for arm in ("v003", "v004"):
        summary = ExperimentSummary.model_validate_json(
            (RESULT_ROOT / arm / "summary.json").read_text(encoding="utf-8")
        )
        metrics = ExperienceMetrics.model_validate_json(
            (RESULT_ROOT / arm / "experience_metrics.json").read_text(encoding="utf-8")
        )
        with (RESULT_ROOT / arm / "summary.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))

        assert len(rows) == summary.total_attempts == summary.valid_evaluated_attempts == 2
        assert sum(row["resolved"] == "True" for row in rows) == summary.resolved_attempts == 1
        assert metrics.retrieval_attempts == metrics.retrieval_hits == 2


def test_train_holdout_comparison_rejects_v004_uplift_claims() -> None:
    comparison = _json(RESULT_ROOT / "comparison.json")
    behavior = _json(RESULT_ROOT / "behavior-comparison.json")

    assert comparison["execution_contract_commit"].startswith("280afbd")
    assert comparison["controlled_conditions_verified"] is True
    assert comparison["selective_reruns_performed"] is False
    assert comparison["total_paid_calls"] == 4
    assert comparison["arms"]["v003"]["resolved"] == 1
    assert comparison["arms"]["v004"]["resolved"] == 1
    assert comparison["paired_outcomes"] == {
        "pairs": 2,
        "v003_wins": 1,
        "v004_wins": 1,
        "ties": 0,
        "two_sided_exact_mcnemar_p": 1.0,
        "rows": [
            {
                "run_id": "run_task_101_r01",
                "v003_resolved": False,
                "v004_resolved": True,
            },
            {
                "run_id": "run_task_101_r02",
                "v003_resolved": True,
                "v004_resolved": False,
            },
        ],
    }
    assert behavior["same_contract_summary"] == {
        "v003_adherent": 2,
        "v004_adherent": 1,
        "v003_rate": 1.0,
        "v004_rate": 0.5,
        "v004_incremental_utilization": 0,
    }
    assert all(
        value is False
        for value in comparison["interpretation"].values()
        if isinstance(value, bool)
    )
    assert comparison["cost"]["conservative_total_usd"] == 0.1302
    assert comparison["cost"]["conservative_total_usd"] < comparison["cost"][
        "authorization_ceiling_usd"
    ]


def test_local_train_holdout_evidence_matches_frozen_hashes_when_present() -> None:
    evidence = _json(RESULT_ROOT / "evidence-manifest.json")
    if not Path("evaluation_runs/exp-experience-v003-train-holdout-v1").is_dir():
        return

    for version in ("v003", "v004"):
        experiment = f"exp-experience-{version}-train-holdout-v1"
        evaluation_root = Path("evaluation_runs") / experiment
        for filename, suffix in (
            ("manifest.json", "manifest"),
            ("summary.json", "summary_json"),
            ("summary.csv", "summary_csv"),
            ("experience_metrics.json", "experience_metrics"),
        ):
            raw = evaluation_root / filename
            assert _sha256(raw) == evidence["arm_artifacts"][f"{version}_{suffix}"]
        for repetition in (1, 2):
            run_label = f"r{repetition:02d}"
            run_root = Path("runs") / experiment / f"run_task_101_{run_label}"
            for filename, suffix in (
                ("retrieval.json", "retrieval"),
                ("trace_features.json", "trace_features"),
                ("final.patch", "final_patch"),
            ):
                assert _sha256(run_root / filename) == evidence["run_artifacts"][
                    f"{version}_{run_label}_{suffix}"
                ]
            report = (
                evaluation_root
                / "instances/task_101"
                / f"attempt_{repetition:02d}/report.json"
            )
            assert _sha256(report) == evidence["run_artifacts"][
                f"{version}_{run_label}_evaluation_report"
            ]
