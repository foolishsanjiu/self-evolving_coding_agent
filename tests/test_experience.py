from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from evodev.benchmark import BenchmarkLoader, BenchmarkTask, BenchmarkTaskConfig
from evodev.config import load_settings
from evodev.evaluation import EvaluationGrades, EvaluationResult, FailureType
from evodev.experience import (
    EvidenceKind,
    EvidenceReference,
    ExperienceCandidate,
    ExperienceStatus,
    ExperienceStore,
    Reflection,
    ReflectionContext,
    ReflectionContextBuilder,
    ReflectionExtractor,
    StructuredReflection,
    StructuredReflectionDraft,
    can_write_experience,
    is_reflection_eligible,
)
from evodev.experience.generate import (
    ExperienceGenerationRunner,
    build_experience_generation_plan,
    require_reflection_paid_confirmation,
)
from evodev.llm import ModelTurn
from evodev.trajectory.models import utc_now


def _context() -> ReflectionContext:
    return ReflectionContext(
        task_id="task_002",
        run_id="run_task_002_r01",
        task_description="Handle invalid input robustly.",
        task_type="exception_handling",
        evaluation_failure=FailureType.TARGET_TEST_FAILED,
        final_patch_summary="files=['ports.py']; additions=5; deletions=1",
        relevant_test_failure="expected stable ValueError for out-of-range input",
        behavioral_features={
            "searched_before_edit": False,
            "inspected_tests_before_edit": True,
            "unique_files_read": 1,
            "patch_attempts": 5,
            "test_runs": 4,
        },
        important_events=[
            {"seq": 3, "type": "TOOL_CALL", "tool": "apply_patch", "success": None}
        ],
        allowed_evidence_references=[
            "event:3",
            "feature:patch_attempts",
            "evaluator:failure_type",
        ],
    )


def _output(reflection_id: str = "reflection_1") -> StructuredReflection:
    return StructuredReflection(
        reflection=Reflection(
            reflection_id=reflection_id,
            task_id="task_002",
            run_id="run_task_002_r01",
            failure_type=FailureType.TARGET_TEST_FAILED,
            evidence=[
                EvidenceReference(
                    kind=EvidenceKind.EVALUATOR_RESULT,
                    reference="evaluator:failure_type",
                ),
                EvidenceReference(
                    kind=EvidenceKind.BEHAVIORAL_FEATURE,
                    reference="feature:patch_attempts",
                ),
            ],
            root_cause="Input domain requirements were not enumerated before editing.",
            bad_strategy="Patched individual examples without defining the validation contract.",
            better_strategy="Enumerate invalid input classes and verify each boundary.",
            confidence=0.8,
        ),
        experience_candidate=ExperienceCandidate(
            task_types=["exception_handling"],
            trigger="When parsing bounded user input with several invalid classes",
            recommendation="List type, format, and range cases before implementing validation.",
            rationale="A complete input partition prevents example-by-example patching.",
            keywords=["validation", "range", "input"],
            confidence=0.8,
        ),
    )


class FakeReflectionModel:
    def __init__(self, output: StructuredReflection) -> None:
        self.output = output
        self.calls = 0
        self.messages = []

    def generate(self, messages, tools=None) -> ModelTurn:
        self.calls += 1
        self.messages.append(messages)
        payload = self.output.model_dump()
        reflection = payload["reflection"]
        for trusted_field in ("reflection_id", "task_id", "run_id", "created_at"):
            reflection.pop(trusted_field)
        draft = StructuredReflectionDraft.model_validate(payload)
        return ModelTurn(content=draft.model_dump_json())


@pytest.fixture
def experience_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"experience_{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def test_eligibility_excludes_infrastructure_and_split_policy() -> None:
    assert is_reflection_eligible(FailureType.TARGET_TEST_FAILED)
    assert is_reflection_eligible(FailureType.AGENT_MAX_STEPS)
    assert not is_reflection_eligible(FailureType.ENVIRONMENT_ERROR)
    assert not is_reflection_eligible(FailureType.EVALUATION_TIMEOUT)
    assert can_write_experience("train")
    assert not can_write_experience("validation")
    assert not can_write_experience("test")


def test_one_call_extracts_two_validated_objects_without_raw_trace() -> None:
    output = _output()
    output.experience_candidate.task_types = ["generated_input_validation"]
    model = FakeReflectionModel(output)
    result = ReflectionExtractor(model).extract(_context())

    assert model.calls == 1
    assert result.reflection.root_cause
    assert result.experience_candidate.recommendation
    assert result.experience_candidate.task_types == [
        "exception_handling",
        "generated_input_validation",
    ]
    prompt = json.dumps(model.messages)
    assert "allowed_evidence_references" in prompt
    assert "events.jsonl" not in prompt


def test_context_builder_keeps_only_bounded_public_evidence(experience_root: Path) -> None:
    task = next(
        task
        for task in BenchmarkLoader(Path("benchmarks")).load_tasks()
        if task.config.task_id == "task_002"
    )
    run_path = experience_root / "run"
    evaluation_path = experience_root / "evaluation"
    run_path.mkdir()
    evaluation_path.mkdir()
    events = [
        {
            "seq": index,
            "type": "TOOL_CALL",
            "data": {
                "tool_call": {
                    "name": "apply_patch" if index > 1 else "read_file",
                    "arguments": {"path": "tests/test_public.py"},
                }
            },
        }
        for index in range(1, 6)
    ]
    (run_path / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )
    (run_path / "final.patch").write_text(
        "--- a/ports.py\n+++ b/ports.py\n-old\n+new\n", encoding="utf-8"
    )
    (evaluation_path / "test_output.txt").write_text("x" * 100, encoding="utf-8")
    result = EvaluationResult(
        task_id="task_002",
        agent_run_id="run_task_002_r01",
        benchmark_version="1.0",
        benchmark_hash="b" * 64,
        grades=EvaluationGrades(patch_exists=True, patch_applies=True, syntax_valid=True),
        failure_type=FailureType.TARGET_TEST_FAILED,
        resolved=False,
        valid_evaluation=True,
        started_at=utc_now(),
        duration_ms=1,
    )

    context = ReflectionContextBuilder(max_events=2, max_failure_chars=20).build(
        task, result, run_path, evaluation_path
    )

    assert len(context.important_events) == 2
    assert len(context.relevant_test_failure) == 20
    assert len(context.behavioral_features) == 5
    assert context.final_patch_summary == "files=['ports.py']; additions=1; deletions=1"
    assert "event:5" in context.allowed_evidence_references


def test_extractor_rejects_untraceable_evidence_and_task_answers() -> None:
    unknown = _output()
    unknown.reflection.evidence[0].reference = "event:999"
    with pytest.raises(ValueError, match="unknown evidence"):
        ReflectionExtractor(FakeReflectionModel(unknown)).extract(_context())

    answer = _output()
    answer.experience_candidate.recommendation = "Use the gold patch for task_002"
    with pytest.raises(ValueError, match="task-specific"):
        ReflectionExtractor(FakeReflectionModel(answer)).extract(_context())


def test_train_store_merges_similar_experience_and_preserves_provenance(
    experience_root: Path,
) -> None:
    store = ExperienceStore(experience_root / "experience.sqlite")
    first = _output("reflection_1")
    first_id = store.add_or_merge(
        first.experience_candidate,
        first.reflection,
        split="train",
        trajectory_path=Path("runs/run_1"),
        evaluation_report_path=Path("evaluation/task_002/report.json"),
    )
    second = _output("reflection_2")
    second.reflection.run_id = "run_task_002_r02"
    second.experience_candidate.confidence = 0.9
    second_id = store.add_or_merge(
        second.experience_candidate,
        second.reflection,
        split="train",
        trajectory_path=Path("runs/run_2"),
        evaluation_report_path=Path("evaluation/task_002/report_2.json"),
    )

    assert first_id == second_id
    assert len(store.list_experiences()) == 1
    assert store.list_experiences()[0].confidence == 0.9
    assert store.source_count(first_id) == 2
    store.set_status(first_id, ExperienceStatus.DEPRECATED)
    assert store.list_experiences()[0].status == ExperienceStatus.DEPRECATED
    store.close()

    read_only = ExperienceStore(experience_root / "experience.sqlite", read_only=True)
    assert len(read_only.list_sources()) == 2
    with pytest.raises(PermissionError, match="opened read-only"):
        read_only.set_status(first_id, ExperienceStatus.ACTIVE)
    with pytest.raises(PermissionError, match="opened read-only"):
        read_only.add_or_merge(
            second.experience_candidate,
            second.reflection,
            split="train",
            trajectory_path=Path("runs/run_2"),
            evaluation_report_path=Path("evaluation/report_2.json"),
        )
    read_only.close()


@pytest.mark.parametrize("split", ["validation", "test"])
def test_non_train_splits_cannot_write(experience_root: Path, split: str) -> None:
    store = ExperienceStore(experience_root / f"{split}.sqlite")
    output = _output()
    with pytest.raises(PermissionError, match="read-only"):
        store.add_or_merge(
            output.experience_candidate,
            output.reflection,
            split=split,
            trajectory_path=Path("runs/run"),
            evaluation_report_path=Path("evaluation/report.json"),
        )
    assert store.list_experiences() == []
    store.close()


def test_generation_runner_writes_once_and_skips_existing_run(
    experience_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = BenchmarkTask(
        split="train",
        config=BenchmarkTaskConfig(
            task_id="task_002",
            category="exception_handling",
            difficulty="easy",
            description="Handle invalid input robustly.",
            expected_behavior="Reject invalid input.",
            repository_template="runner_fixture",
        ),
        task_path=experience_root / "benchmark",
        repository_path=experience_root / "repo",
        public_tests_path=experience_root / "tests",
        hidden_target_tests_path=experience_root / "target",
        hidden_regression_tests_path=experience_root / "regression",
        gold_patch_path=experience_root / "gold.patch",
    )

    class FakeLoader:
        def __init__(self, root: Path) -> None:
            self.root = root

        def load_tasks(self) -> list[BenchmarkTask]:
            return [task]

        def verify_manifest(self):
            return SimpleNamespace(benchmark_version="1.0", manifest_hash="b" * 64)

    monkeypatch.setattr("evodev.experience.generate.BenchmarkLoader", FakeLoader)
    run_path = experience_root / "runs" / "exp-test" / "run_task_002_r01"
    report_path = experience_root / "evaluation_runs" / "exp-test" / "instances" / "task_002"
    run_path.mkdir(parents=True)
    report_path.mkdir(parents=True)
    (run_path / "events.jsonl").write_text("", encoding="utf-8")
    (run_path / "final.patch").write_text("", encoding="utf-8")
    (report_path / "test_output.txt").write_text("target failed", encoding="utf-8")
    result = EvaluationResult(
        task_id="task_002",
        agent_run_id="run_task_002_r01",
        benchmark_version="1.0",
        benchmark_hash="b" * 64,
        grades=EvaluationGrades(),
        failure_type=FailureType.TARGET_TEST_FAILED,
        resolved=False,
        valid_evaluation=True,
        started_at=utc_now(),
        duration_ms=1,
    )
    (report_path / "report.json").write_text(result.model_dump_json(), encoding="utf-8")
    model = FakeReflectionModel(_output())
    plan = build_experience_generation_plan(
        experience_root,
        load_settings(Path("configs")),
        experiment_id="exp-test",
        database_path=experience_root / "experience.sqlite",
        benchmark_root=experience_root / "benchmark",
    )
    runner = ExperienceGenerationRunner(
        experience_root,
        "exp-test",
        experience_root / "experience.sqlite",
        extractor=ReflectionExtractor(model),
    )

    assert plan.expected_paid_calls == 1
    assert [run.run_id for run in plan.runs] == ["run_task_002_r01"]

    first = runner.run(task_id="task_002")
    second = runner.run(task_id="task_002")

    assert len(first["generated"]) == 1
    assert second["skipped"] == [
        {"task_id": "task_002", "reason": "already_reflected"}
    ]
    assert model.calls == 1

    class RejectingExtractor:
        last_turn = ModelTurn(input_tokens=10, output_tokens=5)

        def extract(self, context):
            raise ValueError("candidate failed local validation")

    rejected = ExperienceGenerationRunner(
        experience_root,
        "exp-test",
        experience_root / "rejected.sqlite",
        extractor=RejectingExtractor(),
    ).run(selected_run_ids={"run_task_002_r01"})

    assert rejected["generated"] == []
    assert rejected["rejected"] == [
        {
            "task_id": "task_002",
            "run_id": "run_task_002_r01",
            "reason": "candidate failed local validation",
            "input_tokens": 10,
            "output_tokens": 5,
        }
    ]
    assert rejected["input_tokens"] == 10
    assert rejected["output_tokens"] == 5


def test_reflection_cli_requires_explicit_paid_confirmation() -> None:
    with pytest.raises(PermissionError, match="--confirm-paid"):
        require_reflection_paid_confirmation(False)

    require_reflection_paid_confirmation(True)
