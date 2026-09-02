"""Generate eligible Train reflections from an evaluated experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evodev.benchmark import BenchmarkLoader
from evodev.config import load_settings
from evodev.evaluation import EvaluationResult
from evodev.experience.context import ReflectionContextBuilder
from evodev.experience.eligibility import is_reflection_eligible
from evodev.experience.extractor import ReflectionExtractor
from evodev.experience.store import ExperienceStore
from evodev.llm import LLMClient


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
    def _skip_reason(split: str, result: EvaluationResult, store: ExperienceStore) -> str | None:
        if split != "train":
            return "memory_read_only"
        if not is_reflection_eligible(result.failure_type):
            return "failure_not_eligible"
        if store.has_run(result.task_id, result.agent_run_id):
            return "already_reflected"
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract reusable experience from failures.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--experiment-id", default="exp-baseline-v1")
    parser.add_argument("--task-id")
    parser.add_argument("--database", type=Path, default=Path("data/experience.sqlite"))
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    database = arguments.database
    if not database.is_absolute():
        database = project_root / database
    summary = ExperienceGenerationRunner(
        project_root,
        arguments.experiment_id,
        database,
        benchmark_root=arguments.benchmark_root,
    ).run(task_id=arguments.task_id)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
