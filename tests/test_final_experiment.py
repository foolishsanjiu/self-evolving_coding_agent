from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError

from evodev.config import load_settings
from evodev.evaluation.final_experiment import (
    FinalExperimentConfig,
    FinalExperimentPlanner,
    FinalRunResult,
    FinalRuntimeIdentity,
    FinalVariantId,
    load_final_experiment_config,
    summarize_final_results,
    write_frozen_final_manifest,
)

CONFIG_PATH = Path("configs/experiments/final-v1.yaml")


def _identity(*, clean: bool = True) -> FinalRuntimeIdentity:
    return FinalRuntimeIdentity(
        git_commit="a" * 40,
        git_clean=clean,
        sandbox_digest="sha256:final-image",
        tool_catalog_hash="b" * 64,
    )


def _preflight():
    config = load_final_experiment_config(CONFIG_PATH)
    return FinalExperimentPlanner(
        Path("."),
        load_settings(Path("configs")),
        config,
    ).preflight(_identity())


def test_final_config_is_the_exact_fixed_2x2_matrix() -> None:
    config = load_final_experiment_config(CONFIG_PATH)

    assert config.benchmark_split == "test"
    assert config.runs_per_task_per_variant == 3
    assert {
        item.variant_id: (
            item.experience_enabled,
            item.evolved_policy_enabled,
        )
        for item in config.variants
    } == {
        FinalVariantId.BASELINE: (False, False),
        FinalVariantId.EXPERIENCE: (True, False),
        FinalVariantId.POLICY: (False, True),
        FinalVariantId.COMBINED: (True, True),
    }

    invalid = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    invalid["variants"][3]["experience_enabled"] = False
    with pytest.raises(ValidationError, match="exact A/B/C/D"):
        FinalExperimentConfig.model_validate(invalid)


def test_preflight_pins_all_identities_and_is_ready_with_two_accepted_cases() -> None:
    preflight = _preflight()
    manifest = preflight.manifest
    variants = {item.variant_id: item for item in manifest.variants}

    assert preflight.ready_to_freeze is True
    assert preflight.accepted_case_studies == 2
    assert preflight.required_accepted_case_studies == 2
    assert preflight.blocking_reasons == []
    assert preflight.expected_agent_runs == 36
    assert manifest.git_commit == "a" * 40
    assert manifest.benchmark_task_ids == ["task_010", "task_011", "task_012"]
    assert manifest.tool_catalog_hash == "b" * 64
    assert variants[FinalVariantId.BASELINE].policy_version == "policy-v001"
    assert variants[FinalVariantId.EXPERIENCE].experience_version == "experience-v001"
    assert variants[FinalVariantId.POLICY].policy_version == "policy-v003"
    assert variants[FinalVariantId.COMBINED].policy_version == "policy-v003"
    assert variants[FinalVariantId.COMBINED].experience_version == "experience-v001"
    assert variants[FinalVariantId.BASELINE].max_steps == 15
    assert variants[FinalVariantId.COMBINED].max_steps == 10
    assert manifest.freeze.policy_evolution_enabled is False
    assert manifest.freeze.selective_reruns_allowed is False


def test_dirty_git_is_an_independent_freeze_blocker() -> None:
    config = load_final_experiment_config(CONFIG_PATH)
    preflight = FinalExperimentPlanner(
        Path("."),
        load_settings(Path("configs")),
        config,
    ).preflight(_identity(clean=False))

    assert "Git working tree is not clean" in preflight.blocking_reasons


def test_manifest_write_requires_a_ready_preflight() -> None:
    preflight = _preflight()
    root = Path(".test_runtime") / f"final_manifest_{uuid4().hex}"
    path = root / "experiment_manifest.json"
    try:
        blocked = preflight.model_copy(
            update={
                "ready_to_freeze": False,
                "blocking_reasons": ["test blocker"],
            }
        )
        with pytest.raises(RuntimeError, match="not ready"):
            write_frozen_final_manifest(blocked, path)

        written = write_frozen_final_manifest(preflight, path)

        assert path.is_file()
        assert write_frozen_final_manifest(preflight, path) == written

        changed_manifest = preflight.manifest.model_copy(update={"model": "changed-model"})
        changed = preflight.model_copy(update={"manifest": changed_manifest})
        with pytest.raises(ValueError, match="other conditions"):
            write_frozen_final_manifest(changed, path)
    finally:
        shutil.rmtree(root)


def _results() -> list[FinalRunResult]:
    results = []
    for variant in FinalVariantId:
        for task_id in ("task_010", "task_011", "task_012"):
            for repetition in range(1, 4):
                resolved = repetition == 1
                results.append(
                    FinalRunResult(
                        variant_id=variant,
                        task_id=task_id,
                        agent_run_id=(
                            f"final-{variant.value}-{task_id}-r{repetition:02d}"
                        ),
                        resolved=resolved,
                        valid_evaluation=True,
                        failure_type=(
                            "RESOLVED" if resolved else "TARGET_TEST_FAILED"
                        ),
                        react_steps=5 if resolved else 10,
                        tool_calls=6 if resolved else 12,
                        tokens=100 if resolved else 200,
                        latency_ms=1_000 if resolved else 2_000,
                        searched_before_edit=resolved,
                        inspected_tests_before_edit=True,
                        patch_attempts=1 if resolved else 3,
                    )
                )
    return results


def test_final_summary_separates_overall_and_resolved_run_efficiency() -> None:
    manifest = _preflight().manifest
    summary = summarize_final_results(manifest, _results())
    baseline = summary.variants[0]

    assert len(summary.variants) == 4
    assert baseline.total_attempts == 9
    assert baseline.valid_attempts == 9
    assert baseline.resolved_attempts == 3
    assert baseline.resolution_rate == 0.3333
    assert baseline.overall_efficiency.average_tokens == 166.6667
    assert baseline.resolved_run_efficiency.average_tokens == 100
    assert baseline.search_before_edit_rate == 0.3333
    assert baseline.test_inspection_before_edit_rate == 1
    assert baseline.average_patch_attempts == 2.3333

    with pytest.raises(ValueError, match="Incomplete Final results"):
        summarize_final_results(manifest, _results()[:-1])
