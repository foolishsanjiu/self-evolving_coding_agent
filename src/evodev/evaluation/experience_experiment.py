"""Validation-only controlled experiments for frozen experience retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

import yaml
from mcp import StdioServerParameters

from evodev import __version__
from evodev.agent import ReActAgent
from evodev.agent.react_agent import SYSTEM_PROMPT
from evodev.benchmark import BenchmarkLoader, BenchmarkTask, BenchmarkTaskConfig
from evodev.config import AppSettings, load_settings
from evodev.evaluation.baseline import _sandbox_digest, _sha256_text
from evodev.evaluation.evaluator import IndependentEvaluator
from evodev.evaluation.experiment import ExperimentReporter
from evodev.evaluation.models import (
    EvaluationRequest,
    EvaluationResult,
    ExperimentManifest,
    ExperimentSummary,
)
from evodev.experience import (
    ExperienceMetrics,
    build_retrieval_query,
    build_versioned_retriever,
    load_snapshot,
    summarize_experience_metrics,
)
from evodev.llm import LLMClient
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash

RetrievalMode = Literal["relevant", "random"]
RetrievalAuditSplit = Literal["train", "validation"]


def _resolve_under_root(project_root: Path, path: Path) -> tuple[Path, str]:
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    return resolved, resolved.relative_to(project_root).as_posix()


def _load_public_tasks(
    loader: BenchmarkLoader, split: RetrievalAuditSplit
) -> list[BenchmarkTask]:
    manifest = loader.load_manifest()
    if manifest.benchmark_version != loader.definition.benchmark_version:
        raise ValueError("Benchmark definition and manifest versions differ")
    entries = {
        item.task_id: item for item in manifest.tasks if item.split == split
    }
    tasks = []
    split_root = loader.root / split
    for task_path in sorted(split_root.glob("task_*")):
        if not task_path.is_dir():
            continue
        config = BenchmarkTaskConfig.model_validate(
            yaml.safe_load((task_path / "task.yaml").read_text(encoding="utf-8"))
        )
        entry = entries.get(config.task_id)
        if entry is None or (
            entry.category != config.category
            or entry.repository_template != config.repository_template
        ):
            raise ValueError(f"Public {split} task differs from manifest: {config.task_id}")
        repository = (task_path / "repo").resolve(strict=True)
        tasks.append(
            BenchmarkTask(
                split=split,
                config=config,
                task_path=task_path.resolve(),
                repository_path=repository,
                public_tests_path=repository / "tests",
                hidden_target_tests_path=task_path / "hidden_tests" / "target",
                hidden_regression_tests_path=task_path / "hidden_tests" / "regression",
                gold_patch_path=task_path / "gold.patch",
            )
        )
    if {task.config.task_id for task in tasks} != set(entries):
        raise ValueError(f"{split} public task inventory differs from manifest")
    return tasks


def _select_public_tasks(
    loader: BenchmarkLoader,
    split: RetrievalAuditSplit,
    task_ids: list[str] | None = None,
) -> list[BenchmarkTask]:
    tasks = _load_public_tasks(loader, split)
    if task_ids is None:
        return tasks
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Selected task IDs must be unique")
    selected = set(task_ids)
    available = {task.config.task_id for task in tasks}
    unknown = sorted(selected - available)
    if unknown:
        raise ValueError(f"Selected tasks are not in the {split} split: {unknown}")
    return [task for task in tasks if task.config.task_id in selected]


def audit_retrieval(
    project_root: Path,
    snapshot_path: Path,
    benchmark_root: Path,
    *,
    split: RetrievalAuditSplit,
    top_k: int = 3,
    max_chars: int = 2_500,
) -> dict[str, object]:
    root = project_root.resolve()
    resolved_snapshot, relative_snapshot = _resolve_under_root(root, snapshot_path)
    resolved_benchmark, relative_benchmark = _resolve_under_root(root, benchmark_root)
    snapshot = load_snapshot(resolved_snapshot)
    loader = BenchmarkLoader(resolved_benchmark)
    manifest = loader.load_manifest()
    retriever = build_versioned_retriever(
        snapshot.experiences,
        snapshot.sources,
        top_k=top_k,
        max_chars=max_chars,
    )
    tasks = []
    selected_ids = set()
    for task in _load_public_tasks(loader, split):
        result = retriever.retrieve(build_retrieval_query(task), "relevant")
        selections = [
            {
                "experience_id": item.experience.experience_id,
                "score": item.score,
                "task_type_match": item.task_type_match,
                "keyword_overlap": item.keyword_overlap,
                "trigger_match": item.trigger_match,
            }
            for item in result.selected
        ]
        selected_ids.update(item["experience_id"] for item in selections)
        tasks.append(
            {
                "task_id": task.config.task_id,
                "category": task.config.category,
                "hit": result.hit,
                "prompt_chars": result.prompt_chars,
                "selected": selections,
            }
        )
    if not tasks:
        raise ValueError(f"Selected Benchmark has no {split} tasks")
    hit_tasks = sum(bool(task["hit"]) for task in tasks)
    return {
        "benchmark_root": relative_benchmark,
        "benchmark_version": manifest.benchmark_version,
        "benchmark_hash": manifest.manifest_hash,
        "snapshot_path": relative_snapshot,
        "experience_version": snapshot.version,
        "experience_hash": snapshot.content_hash,
        "split": split,
        "public_metadata_only": True,
        "task_count": len(tasks),
        "hit_tasks": hit_tasks,
        "hit_rate": round(hit_tasks / len(tasks), 4),
        "average_prompt_chars": round(
            sum(int(task["prompt_chars"]) for task in tasks) / len(tasks), 4
        ),
        "unique_selected_experiences": sorted(selected_ids),
        "tasks": tasks,
    }


def audit_validation_retrieval(
    project_root: Path,
    snapshot_path: Path,
    benchmark_root: Path,
    *,
    top_k: int = 3,
    max_chars: int = 2_500,
) -> dict[str, object]:
    return audit_retrieval(
        project_root,
        snapshot_path,
        benchmark_root,
        split="validation",
        top_k=top_k,
        max_chars=max_chars,
    )


def build_experience_arm_preflight(
    project_root: Path,
    settings: AppSettings,
    snapshot_path: Path,
    *,
    experiment_id: str,
    mode: RetrievalMode,
    repetitions: int,
    benchmark_root: Path,
    baseline_manifest_path: Path,
    split: RetrievalAuditSplit = "validation",
    task_ids: list[str] | None = None,
) -> dict[str, object]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    root = project_root.resolve()
    resolved_snapshot, relative_snapshot = _resolve_under_root(root, snapshot_path)
    resolved_benchmark, relative_benchmark = _resolve_under_root(root, benchmark_root)
    resolved_baseline, relative_baseline = _resolve_under_root(root, baseline_manifest_path)
    snapshot = load_snapshot(resolved_snapshot)
    loader = BenchmarkLoader(resolved_benchmark)
    manifest = loader.load_manifest()
    tasks = _select_public_tasks(loader, split, task_ids)
    runs = [
        {
            "task_id": task.config.task_id,
            "repetition": repetition,
            "agent_run_id": f"run_{task.config.task_id}_r{repetition:02d}",
        }
        for repetition in range(1, repetitions + 1)
        for task in tasks
    ]
    baseline_ready = resolved_baseline.is_file()
    if baseline_ready:
        baseline = ExperimentManifest.model_validate_json(
            resolved_baseline.read_text(encoding="utf-8")
        )
        if (
            baseline.benchmark_version != manifest.benchmark_version
            or baseline.benchmark_hash != manifest.manifest_hash
            or baseline.benchmark_splits != [split]
        ):
            raise ValueError(f"Baseline manifest does not match selected {split} split")
    return {
        "experiment_id": experiment_id,
        "benchmark_root": relative_benchmark,
        "benchmark_version": manifest.benchmark_version,
        "benchmark_hash": manifest.manifest_hash,
        "benchmark_splits": [split],
        "task_ids": [task.config.task_id for task in tasks],
        "repetitions": repetitions,
        "expected_paid_calls": len(runs),
        "mode": mode,
        "snapshot_path": relative_snapshot,
        "experience_version": snapshot.version,
        "experience_hash": snapshot.content_hash,
        "experience_consumer": (
            "execution-contract-v1"
            if any(item.execution_contract is not None for item in snapshot.experiences)
            else "legacy-v1"
        ),
        "baseline_manifest_path": relative_baseline,
        "baseline_manifest_ready": baseline_ready,
        "model_provider": settings.model.provider,
        "model": settings.model.model,
        "temperature": settings.model.temperature,
        "policy_version": "fixed-react-v1",
        "policy_hash": _sha256_text(SYSTEM_PROMPT),
        "max_steps": settings.agent.max_steps,
        "context_budget": settings.agent.max_context_chars,
        "requires_paid_confirmation": True,
        "selective_reruns_allowed": False,
        "runs": runs,
    }


def require_experience_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("Experience execution requires --confirm-paid")


def assert_controlled_conditions(
    baseline: ExperimentManifest, treatment: ExperimentManifest
) -> None:
    allowed = {
        "created_at",
        "experiment_id",
        "experiment_version",
        "experience_hash",
        "experience_consumer",
        "experience_max_chars",
        "experience_mode",
        "experience_random_seed",
        "experience_top_k",
        "experience_version",
    }
    baseline_data = baseline.model_dump(exclude=allowed)
    treatment_data = treatment.model_dump(exclude=allowed)
    if baseline_data != treatment_data:
        changed = sorted(
            key for key in baseline_data if baseline_data[key] != treatment_data[key]
        )
        raise ValueError(f"Controlled conditions changed outside Experience: {changed}")


def prepare_validation_baseline(
    project_root: Path,
    *,
    benchmark_root: Path = Path("benchmarks"),
    source_id: str = "exp-baseline-v1",
    target_id: str = "exp-baseline-validation-v1",
) -> tuple[ExperimentManifest, ExperimentSummary]:
    """Derive a no-cost Validation subset from the frozen full baseline."""
    project_root = project_root.resolve()
    resolved_benchmark_root = (
        benchmark_root
        if benchmark_root.is_absolute()
        else project_root / benchmark_root
    ).resolve()
    loader = BenchmarkLoader(resolved_benchmark_root)
    benchmark_manifest = loader.verify_manifest()
    source_manifest = ExperimentManifest.model_validate_json(
        (project_root / "baselines" / source_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        source_manifest.benchmark_version != benchmark_manifest.benchmark_version
        or source_manifest.benchmark_hash != benchmark_manifest.manifest_hash
    ):
        raise ValueError("Source baseline does not match the selected Benchmark")
    manifest = source_manifest.model_copy(
        update={
            "experiment_id": target_id,
            "experiment_version": target_id,
            "benchmark_splits": ["validation"],
        }
    )
    results = []
    trajectories = {}
    validation_task_ids = [
        task.config.task_id
        for task in loader.load_tasks()
        if task.split == "validation"
    ]
    for task_id in validation_task_ids:
        instance = project_root / "evaluation_runs" / source_id / "instances" / task_id
        result = EvaluationResult.model_validate_json(
            (instance / "report.json").read_text(encoding="utf-8")
        )
        results.append(result)
        trajectories[result.agent_run_id] = (
            project_root / "runs" / source_id / result.agent_run_id
        )
    target = project_root / "evaluation_runs" / target_id
    summary = ExperimentReporter(target, manifest).summarize(results, trajectories)
    return manifest, summary


class ExperienceExperimentRunner:
    """Run a frozen relevant or random retrieval arm on one public split."""

    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        snapshot_path: Path,
        *,
        experiment_id: str,
        mode: RetrievalMode,
        repetitions: int = 1,
        random_seed: int = 0,
        baseline_manifest_path: Path | None = None,
        benchmark_root: Path = Path("benchmarks"),
        split: RetrievalAuditSplit = "validation",
        task_ids: list[str] | None = None,
    ) -> None:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        if not settings.experience.enabled:
            raise ValueError("Experience must be enabled for this runner")
        self.project_root = project_root.resolve()
        self.settings = settings
        self.snapshot = load_snapshot(snapshot_path)
        self.experience_consumer = (
            "execution-contract-v1"
            if any(item.execution_contract is not None for item in self.snapshot.experiences)
            else "legacy-v1"
        )
        self.experiment_id = experiment_id
        self.mode = mode
        self.repetitions = repetitions
        self.random_seed = random_seed
        self.split = split
        self.task_ids = task_ids
        baseline_path = baseline_manifest_path or (
            self.project_root
            / "baselines"
            / "exp-baseline-validation-v1"
            / "manifest.json"
        )
        self.baseline_manifest = ExperimentManifest.model_validate_json(
            baseline_path.read_text(encoding="utf-8")
        )
        resolved_benchmark_root = (
            benchmark_root
            if benchmark_root.is_absolute()
            else self.project_root / benchmark_root
        ).resolve()
        self.benchmark_root = resolved_benchmark_root.relative_to(self.project_root).as_posix()
        self.loader = BenchmarkLoader(resolved_benchmark_root)
        self.benchmark_manifest = self.loader.verify_manifest()
        assert_controlled_conditions(
            self.baseline_manifest,
            self._manifest(
                self.baseline_manifest.tool_catalog_hash,
                self.baseline_manifest.sandbox_digest,
            ),
        )
        self.runs_root = self.project_root / "runs" / experiment_id
        self.experiment_path = self.project_root / "evaluation_runs" / experiment_id
        self.agent_workspaces = WorkspaceManager(self.runs_root)
        self.evaluation_workspaces = WorkspaceManager(self.experiment_path / ".workspaces")
        self.retriever = build_versioned_retriever(
            self.snapshot.experiences,
            self.snapshot.sources,
            top_k=settings.experience.top_k,
            max_chars=settings.experience.max_chars,
            random_seed=random_seed,
        )

    def _server(self, workspace: Path, artifacts: Path) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "mcp_servers.devtools.server",
                "--workspace",
                str(workspace),
                "--artifacts",
                str(artifacts),
                "--sandbox-config",
                str(self.project_root / "configs" / "sandbox.yaml"),
            ],
            cwd=str(self.project_root),
        )

    def run(self) -> tuple[ExperimentManifest, ExperimentSummary, ExperienceMetrics]:
        sandbox_digest = _sandbox_digest(self.settings.sandbox.image)
        evaluator = IndependentEvaluator(
            self.loader,
            self.evaluation_workspaces,
            self.settings.sandbox,
            trajectories_root=self.runs_root,
        )
        results = []
        retrievals = {}
        trajectory_paths: dict[str, Path] = {}
        catalog_hash: str | None = None
        llm = LLMClient(self.settings.model)
        selected_tasks = _select_public_tasks(self.loader, self.split, self.task_ids)
        for repetition in range(1, self.repetitions + 1):
            for task in selected_tasks:
                run_id = f"run_{task.config.task_id}_r{repetition:02d}"
                retrieval = self.retriever.retrieve(build_retrieval_query(task), self.mode)
                run = self.loader.create_agent_workspace(
                    task, self.agent_workspaces, run_id=run_id
                )
                (run.run_path / "retrieval.json").write_text(
                    retrieval.model_dump_json(indent=2), encoding="utf-8"
                )
                with MCPToolProvider(self._server(run.workspace_path, run.artifacts_path)) as tools:
                    current_catalog_hash = tool_catalog_hash(tools.list_tools())
                    if catalog_hash is None:
                        catalog_hash = current_catalog_hash
                        assert_controlled_conditions(
                            self.baseline_manifest,
                            self._manifest(catalog_hash, sandbox_digest),
                        )
                    elif catalog_hash != current_catalog_hash:
                        raise RuntimeError("Tool catalog changed during controlled experiment")
                    recorder = TrajectoryRecorder(
                        run.run_path,
                        RunMetadata(
                            run_id=run_id,
                            task_id=task.config.task_id,
                            agent_release=__version__,
                            policy_version="fixed-react-v1",
                            policy_hash=_sha256_text(SYSTEM_PROMPT),
                            experience_version=self.snapshot.version,
                            experience_hash=self.snapshot.content_hash,
                            experience_consumer=self.experience_consumer,
                            model=self.settings.model.model,
                            temperature=self.settings.model.temperature,
                            prompt_version="react-system-v1",
                            max_steps=self.settings.agent.max_steps,
                            context_budget=self.settings.agent.max_context_chars,
                            tool_provider="mcp-devtools-v1",
                            tool_catalog_hash=current_catalog_hash,
                            benchmark_version=self.benchmark_manifest.benchmark_version,
                            benchmark_hash=self.benchmark_manifest.manifest_hash,
                            sandbox_image=self.settings.sandbox.image,
                            sandbox_digest=sandbox_digest,
                        ),
                        env_file=self.project_root / ".env",
                    )
                    agent = ReActAgent(
                        llm=llm,
                        tool_provider=tools,
                        max_steps=self.settings.agent.max_steps,
                        max_tool_retries=self.settings.agent.max_tool_retries,
                        max_context_chars=self.settings.agent.max_context_chars,
                        event_sink=recorder,
                        experience_section=retrieval.prompt_section,
                    )
                    agent.run(self.loader.to_task_spec(task, run.workspace_path))
                self.agent_workspaces.cleanup(run, redact=recorder.redactor.redact_text)
                retrievals[run_id] = retrieval
                trajectory_paths[run_id] = run.run_path
                instance = self.experiment_path / "instances" / task.config.task_id
                if self.repetitions > 1:
                    instance = instance / f"attempt_{repetition:02d}"
                results.append(
                    evaluator.evaluate(
                        EvaluationRequest(
                            task_id=task.config.task_id,
                            final_patch=(run.run_path / "final.patch").read_text(
                                encoding="utf-8"
                            ),
                            agent_run_id=run_id,
                        ),
                        instance,
                    )
                )
        assert catalog_hash is not None
        manifest = self._manifest(catalog_hash, sandbox_digest)
        summary = ExperimentReporter(self.experiment_path, manifest).summarize(
            results, trajectory_paths
        )
        baseline_trajectories = {
            run_id: self.project_root / "runs" / self.baseline_manifest.experiment_id / run_id
            for run_id in retrievals
        }
        experience_metrics = summarize_experience_metrics(
            retrievals, trajectory_paths, baseline_trajectories
        )
        (self.experiment_path / "experience_metrics.json").write_text(
            experience_metrics.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest, summary, experience_metrics

    def _manifest(self, catalog_hash: str, sandbox_digest: str) -> ExperimentManifest:
        return ExperimentManifest(
            experiment_id=self.experiment_id,
            experiment_version=self.experiment_id,
            repetitions=self.repetitions,
            agent_release=__version__,
            policy_version="fixed-react-v1",
            policy_hash=_sha256_text(SYSTEM_PROMPT),
            experience_version=self.snapshot.version,
            experience_hash=self.snapshot.content_hash,
            experience_mode=self.mode,
            experience_consumer=self.experience_consumer,
            experience_top_k=self.settings.experience.top_k,
            experience_max_chars=self.settings.experience.max_chars,
            experience_random_seed=self.random_seed,
            model=self.settings.model.model,
            temperature=self.settings.model.temperature,
            prompt_version="react-system-v1",
            max_steps=self.settings.agent.max_steps,
            context_budget=self.settings.agent.max_context_chars,
            tool_provider="mcp-devtools-v1",
            tool_catalog_hash=catalog_hash,
            sandbox_image=self.settings.sandbox.image,
            sandbox_digest=sandbox_digest,
            benchmark_version=self.benchmark_manifest.benchmark_version,
            benchmark_hash=self.benchmark_manifest.manifest_hash,
            benchmark_root=self.benchmark_root,
            benchmark_splits=[self.split],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a controlled experience arm.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--snapshot", type=Path, default=Path("experiences/experience-v001.json"))
    parser.add_argument("--mode", choices=["relevant", "random"], required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--split", choices=["train", "validation"], default="validation")
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--confirm-paid", action="store_true")
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    snapshot_path = arguments.snapshot
    if not snapshot_path.is_absolute():
        snapshot_path = project_root / snapshot_path
    settings = load_settings(project_root / "configs", project_root / ".env")
    baseline_manifest = arguments.baseline_manifest
    if baseline_manifest is None:
        baseline_manifest = (
            Path("baselines/exp-baseline-validation-v1/manifest.json")
            if arguments.split == "validation"
            else Path("evaluation_runs/exp-baseline-v2-train-v1/manifest.json")
        )
    preflight = build_experience_arm_preflight(
        project_root,
        settings,
        snapshot_path,
        experiment_id=arguments.experiment_id,
        mode=arguments.mode,
        repetitions=arguments.repetitions,
        benchmark_root=arguments.benchmark_root,
        baseline_manifest_path=baseline_manifest,
        split=arguments.split,
        task_ids=arguments.task_ids,
    )
    if arguments.plan:
        print(json.dumps(preflight, indent=2))
        return
    require_experience_paid_confirmation(arguments.confirm_paid)
    if not preflight["baseline_manifest_ready"]:
        raise FileNotFoundError(
            "Controlled baseline manifest is not ready: "
            f"{preflight['baseline_manifest_path']}"
        )
    if not baseline_manifest.is_absolute():
        baseline_manifest = project_root / baseline_manifest
    manifest, summary, metrics = ExperienceExperimentRunner(
        project_root,
        settings,
        snapshot_path,
        experiment_id=arguments.experiment_id,
        mode=arguments.mode,
        repetitions=arguments.repetitions,
        random_seed=arguments.random_seed,
        baseline_manifest_path=baseline_manifest,
        benchmark_root=arguments.benchmark_root,
        split=arguments.split,
        task_ids=arguments.task_ids,
    ).run()
    print(
        json.dumps(
            {
                "manifest": manifest.model_dump(mode="json"),
                "summary": summary.model_dump(mode="json"),
                "experience_metrics": metrics.model_dump(mode="json"),
            },
            indent=2,
        )
    )


def audit_main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit frozen Experience retrieval on public Validation metadata."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--split", choices=["train", "validation"], default="validation")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-chars", type=int, default=2_500)
    arguments = parser.parse_args()
    audit = audit_retrieval(
        arguments.project_root,
        arguments.snapshot,
        arguments.benchmark_root,
        split=arguments.split,
        top_k=arguments.top_k,
        max_chars=arguments.max_chars,
    )
    print(json.dumps(audit, indent=2))


def prepare_main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive the Validation subset of the frozen baseline."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--source-id", default="exp-baseline-v1")
    parser.add_argument("--target-id", default="exp-baseline-validation-v1")
    arguments = parser.parse_args()
    manifest, summary = prepare_validation_baseline(
        arguments.project_root,
        benchmark_root=arguments.benchmark_root,
        source_id=arguments.source_id,
        target_id=arguments.target_id,
    )
    print(
        json.dumps(
            {
                "manifest": manifest.model_dump(mode="json"),
                "summary": summary.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
