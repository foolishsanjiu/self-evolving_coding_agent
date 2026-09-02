import hashlib
import json
from pathlib import Path

import yaml

from evodev.experience import load_snapshot

RESULT_ROOT = Path("experiments/benchmark-v2-experience-validation-v2")
EXPECTED_RETRIEVER_SHA256 = "bb1f50b47462d0d5f8f5af84dc9efd3332d3e493902b79dc72ab128d182499d2"
EXPECTED_EXPERIENCE_HASH = "53f8ce05c569b94f2969aacff64c43a799b19adec52cdad07a1f59611f1006e9"


def test_v003_validation_gate_matches_the_precommitted_decision_rule() -> None:
    plan = yaml.safe_load(
        Path("configs/experiments/benchmark-v2-experience-validation-v2.yaml").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads((RESULT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((RESULT_ROOT / "retrieval-audit.json").read_text(encoding="utf-8"))

    assert manifest["gate_commit"] == "9224f0a6054964b3ef1d74c704170cce55289bf1"
    assert manifest["decision_rule"] == {
        "minimum_hit_tasks": plan["decision_rule"]["minimum_hit_tasks"],
        "total_validation_tasks": plan["decision_rule"]["total_validation_tasks"],
        "minimum_unique_selected_experiences": plan["decision_rule"][
            "minimum_unique_selected_experiences"
        ],
        "maximum_prompt_chars_per_task": plan["decision_rule"]["maximum_prompt_chars_per_task"],
        "all_boundary_checks_must_pass": plan["decision_rule"]["all_boundary_checks_must_pass"],
    }
    assert audit["hit_tasks"] == 4
    assert len(audit["unique_selected_experiences"]) == 6
    assert max(task["prompt_chars"] for task in audit["tasks"]) == 1913
    assert [task["task_id"] for task in audit["tasks"] if not task["hit"]] == ["task_110"]
    assert manifest["criteria"]["all_passed"] is True
    assert manifest["decision"] == "ready_for_paid_authorization"


def test_v003_validation_gate_locks_inputs_without_paid_execution() -> None:
    manifest = json.loads((RESULT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((RESULT_ROOT / "retrieval-audit.json").read_text(encoding="utf-8"))
    retriever_text = Path("src/evodev/experience/retrieval.py").read_text(encoding="utf-8")
    retriever_hash = hashlib.sha256(
        retriever_text.replace("\r\n", "\n").encode("utf-8")
    ).hexdigest()
    snapshot = load_snapshot(Path("experiences/experience-v003.json"))
    snapshot_ids = {experience.experience_id for experience in snapshot.experiences}
    selected_ids = {
        selected["experience_id"] for task in audit["tasks"] for selected in task["selected"]
    }

    assert retriever_hash == EXPECTED_RETRIEVER_SHA256
    assert manifest["retriever"]["canonical_sha256"] == retriever_hash
    assert snapshot.content_hash == EXPECTED_EXPERIENCE_HASH
    assert manifest["inputs"]["experience_hash"] == snapshot.content_hash
    assert selected_ids == set(audit["unique_selected_experiences"])
    assert selected_ids <= snapshot_ids
    assert manifest["post_audit_lock"]["locked"] is True
    assert not any(
        manifest["post_audit_lock"][field]
        for field in (
            "retriever_changes_allowed",
            "snapshot_changes_allowed",
            "task_type_changes_allowed",
            "threshold_or_ranking_changes_allowed",
        )
    )
    assert manifest["execution"] == {
        "decision_bearing_public_audits": 1,
        "model_calls": 0,
        "paid_calls": 0,
        "docker_started": False,
    }
    assert manifest["future_paid_design"]["new_paid_authorization_required"] is True
