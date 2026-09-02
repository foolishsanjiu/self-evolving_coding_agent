import json
from pathlib import Path

import pytest
import yaml

from evodev.benchmark import BenchmarkLoader
from evodev.evaluation.experience_experiment import _load_public_tasks, audit_retrieval
from evodev.experience import (
    ExperienceGuardrails,
    add_execution_guardrails,
    analyze_guardrail_trace,
    build_execution_guard,
    build_retrieval_query,
    build_versioned_retriever,
    experience_consumer_version,
    load_snapshot,
)

V004_HASH = "f71ac3984674ba98e52ae02fd939dbc5bf2d4ad998a7013b547ff756f6054988"
V005_HASH = "622a19135c144e1e9a8b1d787933add4a8299491888e6e31463c1bbc18919602"
RESULT_ROOT = Path("experiments/benchmark-v2-experience-guardrails-v1")


def _guardrails() -> dict[str, ExperienceGuardrails]:
    payload = yaml.safe_load(
        Path("configs/experience-v005-guardrails.yaml").read_text(encoding="utf-8")
    )
    return {
        experience_id: ExperienceGuardrails.model_validate(item)
        for experience_id, item in payload["guardrails"].items()
    }


def test_v005_is_a_deterministic_guardrail_only_migration() -> None:
    source = load_snapshot(Path("experiences/experience-v004.json"))
    frozen = load_snapshot(Path("experiences/experience-v005.json"))
    rebuilt = add_execution_guardrails(source, "experience-v005", _guardrails())
    source_by_id = {item.experience_id: item for item in source.experiences}

    assert source.content_hash == V004_HASH
    assert rebuilt == frozen
    assert frozen.content_hash == V005_HASH
    assert len(frozen.experiences) == 7
    assert all(
        item.execution_contract is not None
        and item.execution_contract.guardrails is not None
        and item.execution_contract.guardrails.verify_after_last_edit
        for item in frozen.experiences
    )
    assert (
        sum(
            item.execution_contract.guardrails.inspect_after_patch_failure
            for item in frozen.experiences
            if item.execution_contract is not None
            and item.execution_contract.guardrails is not None
        )
        == 1
    )
    for item in frozen.experiences:
        source_contract = source_by_id[item.experience_id].execution_contract
        assert item.execution_contract.model_dump(exclude={"guardrails"}) == (
            source_contract.model_dump(exclude={"guardrails"})
        )
    with pytest.raises(ValueError, match="missing="):
        add_execution_guardrails(source, "experience-v005", {})


def test_v005_task_101_activates_both_runtime_guards_without_changing_selection() -> None:
    v004 = load_snapshot(Path("experiences/experience-v004.json"))
    v005 = load_snapshot(Path("experiences/experience-v005.json"))
    task = _load_public_tasks(BenchmarkLoader(Path("benchmarks-v2")), "train")[0]
    query = build_retrieval_query(task)
    old = build_versioned_retriever(v004.experiences, v004.sources).retrieve(query)
    guarded = build_versioned_retriever(v005.experiences, v005.sources).retrieve(query)
    guard = build_execution_guard(guarded)

    assert [item.experience.experience_id for item in guarded.selected] == [
        item.experience.experience_id for item in old.selected
    ]
    assert guarded.hit is True
    assert guarded.prompt_chars > old.prompt_chars
    assert "Harness-enforced guardrails:" in guarded.prompt_section
    assert guard.inspect_after_patch_failure is True
    assert guard.verify_after_last_edit is True
    assert experience_consumer_version(v004.experiences) == "execution-contract-v1"
    assert experience_consumer_version(v005.experiences) == "execution-contract-v2"


def test_guardrail_trace_analysis_counts_only_executed_tests_and_patch_failures() -> None:
    events = [
        {
            "type": "TOOL_CALL",
            "data": {"tool_call": {"name": "apply_patch"}},
        },
        {
            "type": "TOOL_RESULT",
            "data": {
                "result": {
                    "tool_name": "read_file",
                    "success": False,
                    "error_type": "CONTRACT_PRECONDITION_NOT_MET",
                    "data": {"required_action": "run_tests_before_step_budget_expires"},
                }
            },
        },
        {
            "type": "TOOL_RESULT",
            "data": {
                "result": {
                    "tool_name": "apply_patch",
                    "success": False,
                    "error_type": "PATCH_APPLY_FAILED",
                    "data": {},
                }
            },
        },
        {
            "type": "TOOL_CALL",
            "data": {"tool_call": {"name": "apply_patch"}},
        },
        {
            "type": "TOOL_RESULT",
            "data": {
                "result": {
                    "tool_name": "apply_patch",
                    "success": False,
                    "error_type": "CONTRACT_PRECONDITION_NOT_MET",
                    "data": {"required_action": "read_current_file_after_patch_failure"},
                }
            },
        },
        {
            "type": "TOOL_CALL",
            "data": {"tool_call": {"name": "run_tests"}},
        },
        {
            "type": "TOOL_RESULT",
            "data": {
                "result": {
                    "tool_name": "run_tests",
                    "success": False,
                    "error_type": "INVALID_TOOL_ARGUMENTS",
                    "data": {},
                }
            },
        },
        {
            "type": "CONTRACT_BLOCKED",
            "data": {"required_action": "run_tests_after_last_edit"},
        },
        {"type": "RUN_FINISHED", "data": {"status": "MAX_STEPS"}},
    ]

    assert analyze_guardrail_trace(events) == {
        "patch_attempts": 2,
        "patch_failures": 1,
        "uninspected_patch_retries": 1,
        "uninspected_patch_retry_attempts": 1,
        "blocked_uninspected_patch_retries": 1,
        "executed_uninspected_patch_retries": 0,
        "verification_window_blocks": 1,
        "final_answer_blocks": 1,
        "total_contract_blocks": 3,
        "max_consecutive_patch_failures": 1,
        "test_calls": 1,
        "test_executions": 0,
        "last_successful_edit_verified": True,
        "finish_status": "MAX_STEPS",
    }


def test_v005_train_audit_is_public_and_reproducible() -> None:
    frozen = json.loads((RESULT_ROOT / "train-retrieval-audit.json").read_text(encoding="utf-8"))

    assert (
        audit_retrieval(
            Path("."),
            Path("experiences/experience-v005.json"),
            Path("benchmarks-v2"),
            split="train",
        )
        == frozen
    )
    assert frozen["hit_tasks"] == 1
    assert frozen["tasks"][0]["task_id"] == "task_101"
    assert frozen["tasks"][0]["prompt_chars"] == 1431


def test_v005_frozen_attribution_recomputes_from_local_public_events() -> None:
    attribution = json.loads((RESULT_ROOT / "attribution.json").read_text(encoding="utf-8"))
    if not Path("runs/exp-experience-v003-train-holdout-v1").is_dir():
        return

    for version in ("v003", "v004"):
        for run_id, frozen in attribution["runs"][version].items():
            path = (
                Path("runs")
                / f"exp-experience-{version}-train-holdout-v1"
                / run_id
                / "events.jsonl"
            )
            events = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
            ]
            expected = {
                key: value
                for key, value in frozen.items()
                if key not in {"resolved", "failure_type"}
            }
            measured = analyze_guardrail_trace(events)
            assert {key: measured[key] for key in expected} == expected


def test_v005_offline_config_makes_no_performance_claim() -> None:
    config = yaml.safe_load(
        Path("configs/experiments/benchmark-v2-experience-guardrails-v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    audit = json.loads((RESULT_ROOT / "guardrail-audit.json").read_text(encoding="utf-8"))

    assert config["status"] == "offline_complete"
    assert config["boundaries"]["model_calls"] == 0
    assert config["boundaries"]["paid_calls"] == 0
    assert config["decision"]["text_only_v005_rejected"] is True
    assert audit["migration"]["contracts_changed_excluding_guardrails"] == 0
    assert audit["execution"]["performance_claim"] is False
