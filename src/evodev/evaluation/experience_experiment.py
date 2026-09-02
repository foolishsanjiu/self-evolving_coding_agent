"""Validation-only controlled experiments for frozen experience retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from mcp import StdioServerParameters

from evodev import __version__
from evodev.agent import ReActAgent
from evodev.agent.react_agent import SYSTEM_PROMPT
from evodev.benchmark import BenchmarkLoader
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
    ExperienceRetriever,
    build_retrieval_query,
    load_snapshot,
    summarize_experience_metrics,
)
from evodev.llm import LLMClient
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash

RetrievalMode = Literal["relevant", "random"]


def assert_controlled_conditions(
    baseline: ExperimentManifest, treatment: ExperimentManifest
) -> None:
    allowed = {
        "created_at",
        "experiment_id",
        "experiment_version",
        "experience_hash",
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
    """Run a frozen relevant or random retrieval arm on Validation only."""

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
    ) -> None:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        if not settings.experience.enabled:
            raise ValueError("Experience must be enabled for this runner")
        self.project_root = project_root.resolve()
        self.settings = settings
        self.snapshot = load_snapshot(snapshot_path)
        self.experiment_id = experiment_id
        self.mode = mode
        self.repetitions = repetitions
        self.random_seed = random_seed
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
        self.retriever = ExperienceRetriever(
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
        validation_tasks = [
            task for task in self.loader.load_tasks() if task.split == "validation"
        ]
        for repetition in range(1, self.repetitions + 1):
            for task in validation_tasks:
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
            run_id: self.project_root / "runs" / "exp-baseline-v1" / run_id
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
            benchmark_splits=["validation"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Validation experience arm.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--snapshot", type=Path, default=Path("experiences/experience-v001.json"))
    parser.add_argument("--mode", choices=["relevant", "random"], required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--baseline-manifest", type=Path)
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    snapshot_path = arguments.snapshot
    if not snapshot_path.is_absolute():
        snapshot_path = project_root / snapshot_path
    settings = load_settings(project_root / "configs", project_root / ".env")
    baseline_manifest = arguments.baseline_manifest
    if baseline_manifest is not None and not baseline_manifest.is_absolute():
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
