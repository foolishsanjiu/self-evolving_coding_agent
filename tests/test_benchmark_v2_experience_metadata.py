import json
from pathlib import Path

import pytest
import yaml

from evodev.evaluation.experience_experiment import audit_retrieval
from evodev.experience import add_source_task_types, load_snapshot


def _train_categories() -> dict[str, str]:
    categories = {}
    for path in sorted(Path("benchmarks-v2/train").glob("task_*/task.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        categories[task["task_id"]] = task["category"]
    return categories


def test_v003_is_deterministic_source_category_migration() -> None:
    source = load_snapshot(Path("experiences/experience-v002.json"))
    frozen = load_snapshot(Path("experiences/experience-v003.json"))
    rebuilt = add_source_task_types(source, "experience-v003", _train_categories())

    assert rebuilt == frozen
    assert frozen.content_hash == (
        "53f8ce05c569b94f2969aacff64c43a799b19adec52cdad07a1f59611f1006e9"
    )
    assert len(frozen.experiences) == 7
    assert len(frozen.sources) == 8
    with pytest.raises(ValueError, match="Missing source task categories"):
        add_source_task_types(source, "experience-v003", {})


def test_v003_preserves_content_and_adds_every_source_category() -> None:
    source = load_snapshot(Path("experiences/experience-v002.json"))
    target = load_snapshot(Path("experiences/experience-v003.json"))
    categories = _train_categories()
    source_by_id = {item.experience_id: item for item in source.experiences}

    for experience in target.experiences:
        before = source_by_id[experience.experience_id]
        source_categories = {
            categories[item.task_id]
            for item in target.sources
            if item.experience_id == experience.experience_id
        }
        assert source_categories <= set(experience.task_types)
        assert set(before.task_types) <= set(experience.task_types)
        assert experience.model_dump(exclude={"task_types"}) == before.model_dump(
            exclude={"task_types"}
        )
    assert target.sources == source.sources


def test_train_leave_one_task_out_audit_is_private_and_matches_frozen_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accessed: list[Path] = []
    original_read_text = Path.read_text

    def tracked_read_text(path: Path, *args, **kwargs) -> str:
        accessed.append(path.resolve())
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)
    before = audit_retrieval(
        Path("."),
        Path("experiences/experience-v002.json"),
        Path("benchmarks-v2"),
        split="train",
    )
    after = audit_retrieval(
        Path("."),
        Path("experiences/experience-v003.json"),
        Path("benchmarks-v2"),
        split="train",
    )
    frozen = json.loads(
        Path(
            "experiments/benchmark-v2-experience-metadata-v1/"
            "train-retrieval-audit.json"
        ).read_text(encoding="utf-8")
    )

    assert before["hit_tasks"] == frozen["train_leave_one_task_out"]["all_tasks"][
        "v002_hits"
    ]
    assert after["hit_tasks"] == frozen["train_leave_one_task_out"]["all_tasks"][
        "v003_hits"
    ]
    assert [task["task_id"] for task in after["tasks"] if task["hit"]] == [
        "task_101"
    ]
    benchmark_root = Path("benchmarks-v2").resolve()
    benchmark_reads = [
        path.relative_to(benchmark_root)
        for path in accessed
        if path.is_relative_to(benchmark_root)
    ]
    assert all(path.parts[0] not in {"validation", "test"} for path in benchmark_reads)
    assert all("hidden_tests" not in path.parts for path in benchmark_reads)
    assert all(path.name != "gold.patch" for path in benchmark_reads)
