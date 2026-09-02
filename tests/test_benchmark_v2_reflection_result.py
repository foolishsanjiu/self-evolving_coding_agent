import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from evodev.experience import load_snapshot
from evodev.experience.models import Reflection

RESULT_ROOT = Path("experiments/benchmark-v2-reflection-v1")


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_experience_snapshot_is_active_train_only_and_private() -> None:
    snapshot = load_snapshot(Path("experiences/experience-v002.json"))

    assert snapshot.content_hash == (
        "8eb3a05d7a1c7aa655688b74f050951234fb2133dc8183b1c2566c05aa1ae5dd"
    )
    assert len(snapshot.experiences) == 7
    assert len(snapshot.sources) == 8
    assert {item.status.value for item in snapshot.experiences} == {"active"}
    assert {source.task_id for source in snapshot.sources} <= {
        "task_103",
        "task_105",
        "task_106",
        "task_107",
        "task_108",
    }
    assert sum(source.task_id == "task_107" for source in snapshot.sources) == 2
    for source in snapshot.sources:
        for value in (source.trajectory_path, source.evaluation_report_path):
            assert not PurePosixPath(value).is_absolute()
            assert not PureWindowsPath(value).is_absolute()
            assert "D:\\Projects" not in value


def test_v2_reflection_call_ledger_is_complete_and_conservative() -> None:
    manifest = _load_json(RESULT_ROOT / "manifest.json")
    summary = _load_json(RESULT_ROOT / "summary.json")
    calls = summary["call_accounting"]
    usage = summary["accepted_batch_usage"]

    assert calls == {
        "authorized": 9,
        "completed": 9,
        "accepted": 8,
        "rejected": 1,
        "retried": 0,
    }
    assert usage["input_tokens"] == 18956
    assert usage["output_tokens"] == 28806
    peak = (18956 * 0.44 + 28806 * 1.32) / 1_000_000
    assert usage["peak_all_cache_miss_estimate_usd"] == pytest.approx(peak, abs=5e-5)
    assert summary["rejected_call"]["input_tokens"] is None
    assert summary["total_usage"]["actual_billed_cost"] is None
    assert manifest["execution"]["validation_access"] is False
    assert manifest["execution"]["test_access"] is False


def test_v2_accepted_reflections_match_snapshot_provenance() -> None:
    reflection_payload = _load_json(RESULT_ROOT / "reflections.json")
    reflections = [Reflection.model_validate(item) for item in reflection_payload["accepted"]]
    snapshot = load_snapshot(Path("experiences/experience-v002.json"))

    accepted_ids = {item.reflection_id for item in reflections}
    source_ids = {item.reflection_id for item in snapshot.sources}
    run_ids = {item.run_id for item in reflections}
    assert len(reflections) == 8
    assert accepted_ids == source_ids
    assert "run_task_103_r01" not in run_ids
    assert "run_task_108_r01" not in run_ids
