import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from evodev.benchmark import BenchmarkLoader
from evodev.evaluation.experience_experiment import _load_public_tasks, audit_retrieval
from evodev.experience import (
    BehaviorTarget,
    ContractExperienceRetriever,
    ExperienceExecutionContract,
    add_execution_contracts,
    build_retrieval_query,
    load_snapshot,
    summarize_experience_metrics,
)

RESULT_ROOT = Path("experiments/benchmark-v2-experience-consumption-v1")
V004_HASH = "f71ac3984674ba98e52ae02fd939dbc5bf2d4ad998a7013b547ff756f6054988"


@pytest.fixture
def contract_metric_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"contract_metrics_{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def _contracts() -> dict[str, ExperienceExecutionContract]:
    payload = yaml.safe_load(
        Path("configs/experience-v004-contracts.yaml").read_text(encoding="utf-8")
    )
    return {
        experience_id: ExperienceExecutionContract.model_validate(contract)
        for experience_id, contract in payload["contracts"].items()
    }


def test_v004_is_a_deterministic_contract_only_migration() -> None:
    source = load_snapshot(Path("experiences/experience-v003.json"))
    frozen = load_snapshot(Path("experiences/experience-v004.json"))
    rebuilt = add_execution_contracts(source, "experience-v004", _contracts())
    source_by_id = {item.experience_id: item for item in source.experiences}

    assert rebuilt == frozen
    assert frozen.content_hash == V004_HASH
    assert len(frozen.experiences) == 7
    assert all(item.execution_contract is not None for item in frozen.experiences)
    assert (
        sum(
            len(item.execution_contract.behavior_targets)
            for item in frozen.experiences
            if item.execution_contract is not None
        )
        == 16
    )
    for item in frozen.experiences:
        assert item.model_dump(exclude={"execution_contract"}) == source_by_id[
            item.experience_id
        ].model_dump(exclude={"execution_contract"})
    with pytest.raises(ValueError, match="missing="):
        add_execution_contracts(source, "experience-v004", {})
    with pytest.raises(ValueError, match="integer"):
        BehaviorTarget(feature="test_runs", operator="gte", value=True)


def test_v004_train_audit_is_public_reproducible_and_contract_formatted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accessed: list[Path] = []
    original_read_text = Path.read_text

    def tracked_read_text(path: Path, *args, **kwargs) -> str:
        accessed.append(path.resolve())
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)
    audit = audit_retrieval(
        Path("."),
        Path("experiences/experience-v004.json"),
        Path("benchmarks-v2"),
        split="train",
    )
    frozen = json.loads((RESULT_ROOT / "train-retrieval-audit.json").read_text(encoding="utf-8"))
    snapshot = load_snapshot(Path("experiences/experience-v004.json"))
    retriever = ContractExperienceRetriever(snapshot.experiences, snapshot.sources)
    task = _load_public_tasks(BenchmarkLoader(Path("benchmarks-v2")), "train")[0]
    retrieval = retriever.retrieve(build_retrieval_query(task))

    assert audit == frozen
    assert audit["hit_tasks"] == 1
    assert retrieval.hit is True
    assert retrieval.prompt_chars == 1177
    assert retrieval.prompt_section.startswith("Relevant Experience Execution Contracts:")
    assert "Inspect before editing:" in retrieval.prompt_section
    assert "Verify before finishing:" in retrieval.prompt_section
    assert all(item.execution_targets for item in retrieval.selected)
    benchmark_root = Path("benchmarks-v2").resolve()
    benchmark_reads = [
        path.relative_to(benchmark_root) for path in accessed if path.is_relative_to(benchmark_root)
    ]
    assert all(path.parts[0] not in {"validation", "test"} for path in benchmark_reads)
    assert all("hidden_tests" not in path.parts for path in benchmark_reads)
    assert all(path.name != "gold.patch" for path in benchmark_reads)


def test_contract_metrics_separate_adherence_from_incremental_utilization(
    contract_metric_root: Path,
) -> None:
    snapshot = load_snapshot(Path("experiences/experience-v004.json"))
    retriever = ContractExperienceRetriever(snapshot.experiences, snapshot.sources)
    task = _load_public_tasks(BenchmarkLoader(Path("benchmarks-v2")), "train")[0]
    retrieval = retriever.retrieve(build_retrieval_query(task))
    treatment = contract_metric_root / "treatment"
    baseline = contract_metric_root / "baseline"
    treatment.mkdir()
    baseline.mkdir()
    (treatment / "trace_features.json").write_text(
        '{"inspected_tests_before_edit":true,"unique_files_read":2,"test_runs":1}',
        encoding="utf-8",
    )
    (baseline / "trace_features.json").write_text(
        '{"inspected_tests_before_edit":true,"unique_files_read":2,"test_runs":0}',
        encoding="utf-8",
    )

    metrics = summarize_experience_metrics(
        {"run_task_101_r01": retrieval},
        {"run_task_101_r01": treatment},
        {"run_task_101_r01": baseline},
    )

    assert metrics.measurable_retrievals == 1
    assert metrics.adherent_retrievals == 1
    assert metrics.experience_adherence_rate == 1
    assert metrics.utilized_retrievals == 1
    assert metrics.experience_utilization_rate == 1
