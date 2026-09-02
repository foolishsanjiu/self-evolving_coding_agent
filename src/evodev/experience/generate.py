"""Generate eligible Train reflections from an evaluated experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evodev.benchmark import BenchmarkLoader
from evodev.config import AppSettings, load_settings
from evodev.evaluation import EvaluationResult, FailureType
from evodev.experience.context import ReflectionContextBuilder
from evodev.experience.eligibility import is_reflection_eligible
from evodev.experience.extractor import ReflectionExtractor
from evodev.experience.store import ExperienceStore
from evodev.llm import LLMClient


class ReflectionRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    run_id: str
    failure_type: FailureType


class ExperienceGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    benchmark_root: str
    benchmark_version: str
    benchmark_hash: str
    benchmark_splits: list[Literal["train"]] = Field(default_factory=lambda: ["train"])
    database: str
    model_provider: str
    model: str
    temperature: float = Field(ge=0, le=2)
    expected_paid_calls: int = Field(ge=0)
    runs: list[ReflectionRunSpec]
    skipped: list[dict[str, str]]
    requires_paid_confirmation: Literal[True] = True


def require_reflection_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("Reflection generation requires --confirm-paid")


def build_experience_generation_plan(
    project_root: Path,
    settings: AppSettings,
    *,
    experiment_id: str,
    database_path: Path,
    benchmark_root: Path,
) -> ExperienceGenerationPlan:
    root = project_root.resolve()
    resolved_benchmark = (
        benchmark_root.resolve()
        if benchmark_root.is_absolute()
        else (root / benchmark_root).resolve()
    )
    resolved_database = (
        database_path.resolve()
        if database_path.is_absolute()
        else (root / database_path).resolve()
    )
    loader = BenchmarkLoader(resolved_benchmark)
    manifest = loader.verify_manifest()
    tasks = {task.config.task_id: task for task in loader.load_tasks()}
    store = (
        ExperienceStore(resolved_database, read_only=True)
        if resolved_database.is_file()
        else None
    )
    runs = []
    skipped = []
    try:
        reports_root = root / "evaluation_runs" / experiment_id / "instances"
        if not reports_root.is_dir():
            raise FileNotFoundError(f"Evaluation experiment not found: {experiment_id}")
        for report_path in sorted(reports_root.rglob("report.json")):
            result = EvaluationResult.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            task = tasks.get(result.task_id)
            if task is None:
                raise ValueError(f"Unknown benchmark task in evaluation: {result.task_id}")
            reason = ExperienceGenerationRunner._skip_reason(task.split, result, store)
            if reason:
                skipped.append(
                    {"task_id": result.task_id, "run_id": result.agent_run_id, "reason": reason}
                )
                continue
            runs.append(
                ReflectionRunSpec(
                    task_id=result.task_id,
                    run_id=result.agent_run_id,
                    failure_type=result.failure_type,
                )
            )
    finally:
        if store is not None:
            store.close()
    return ExperienceGenerationPlan(
        experiment_id=experiment_id,
        benchmark_root=resolved_benchmark.relative_to(root).as_posix(),
        benchmark_version=manifest.benchmark_version,
        benchmark_hash=manifest.manifest_hash,
        database=resolved_database.relative_to(root).as_posix(),
        model_provider=settings.model.provider,
        model=settings.model.model,
        temperature=settings.model.temperature,
        expected_paid_calls=len(runs),
        runs=runs,
        skipped=skipped,
    )


class ExperienceGenerationRunner:
    """Run one structured call per eligible, previously unseen Train failure."""

    def __init__(
        self,
        project_root: Path,
        experiment_id: str,
        database_path: Path,
        extractor: ReflectionExtractor | None = None,
        benchmark_root: Path = Path("benchmarks"),
    ) -> None:
        self.project_root = project_root.resolve()
        self.experiment_id = experiment_id
        self.database_path = database_path
        self.extractor = extractor
        self.benchmark_root = benchmark_root

    def run(self, task_id: str | None = None) -> dict[str, object]:
        root = (
            self.benchmark_root
            if self.benchmark_root.is_absolute()
            else self.project_root / self.benchmark_root
        )
        loader = BenchmarkLoader(root)
        tasks = {task.config.task_id: task for task in loader.load_tasks()}
        extractor = self.extractor
        if extractor is None:
            settings = load_settings(self.project_root / "configs", self.project_root / ".env")
            extractor = ReflectionExtractor(LLMClient(settings.model))
        store = ExperienceStore(self.database_path)
        generated: list[dict[str, object]] = []
        skipped: list[dict[str, str]] = []
        input_tokens = 0
        output_tokens = 0
        reports_root = (
            self.project_root / "evaluation_runs" / self.experiment_id / "instances"
        )
        try:
            for report_path in sorted(reports_root.rglob("report.json")):
                result = EvaluationResult.model_validate_json(
                    report_path.read_text(encoding="utf-8")
                )
                if task_id is not None and result.task_id != task_id:
                    continue
                task = tasks[result.task_id]
                reason = self._skip_reason(task.split, result, store)
                if reason:
                    skipped.append({"task_id": result.task_id, "reason": reason})
                    continue
                run_path = (
                    self.project_root / "runs" / self.experiment_id / result.agent_run_id
                )
                context = ReflectionContextBuilder().build(
                    task, result, run_path, report_path.parent
                )
                structured = extractor.extract(context)
                experience_id = store.add_or_merge(
                    structured.experience_candidate,
                    structured.reflection,
                    split=task.split,
                    trajectory_path=run_path,
                    evaluation_report_path=report_path,
                )
                if extractor.last_turn is not None:
                    input_tokens += extractor.last_turn.input_tokens
                    output_tokens += extractor.last_turn.output_tokens
                generated.append(
                    {
                        "task_id": result.task_id,
                        "run_id": result.agent_run_id,
                        "reflection_id": structured.reflection.reflection_id,
                        "experience_id": experience_id,
                    }
                )
        finally:
            store.close()
        return {
            "experiment_id": self.experiment_id,
            "generated": generated,
            "skipped": skipped,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    @staticmethod
    def _skip_reason(
        split: str,
        result: EvaluationResult,
        store: ExperienceStore | None,
    ) -> str | None:
        if split != "train":
            return "memory_read_only"
        if not is_reflection_eligible(result.failure_type):
            return "failure_not_eligible"
        if store is not None and store.has_run(result.task_id, result.agent_run_id):
            return "already_reflected"
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract reusable experience from failures.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--experiment-id", default="exp-baseline-v1")
    parser.add_argument("--task-id")
    parser.add_argument("--database", type=Path, default=Path("data/experience.sqlite"))
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--confirm-paid", action="store_true")
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    settings = load_settings(project_root / "configs", project_root / ".env")
    database = arguments.database
    if not database.is_absolute():
        database = project_root / database
    plan = build_experience_generation_plan(
        project_root,
        settings,
        experiment_id=arguments.experiment_id,
        database_path=database,
        benchmark_root=arguments.benchmark_root,
    )
    if arguments.plan:
        print(plan.model_dump_json(indent=2))
        return
    require_reflection_paid_confirmation(arguments.confirm_paid)
    summary = ExperienceGenerationRunner(
        project_root,
        arguments.experiment_id,
        database,
        benchmark_root=arguments.benchmark_root,
    ).run(task_id=arguments.task_id)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
