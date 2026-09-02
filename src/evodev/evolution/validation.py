"""Controlled Policy experiments and 3x3 pairwise Validation."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from mcp import StdioServerParameters

from evodev import __version__
from evodev.agent import ReActAgent
from evodev.benchmark import BenchmarkLoader
from evodev.config import AppSettings
from evodev.evaluation.baseline import _sandbox_digest
from evodev.evaluation.evaluator import IndependentEvaluator
from evodev.evaluation.experiment import ExperimentReporter
from evodev.evaluation.models import EvaluationRequest, ExperimentManifest
from evodev.llm import LLMClient
from evodev.policy.models import VersionedPolicy
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash

from .gates import compare_pairwise_validation
from .models import PairwiseGateReport, PolicyArmMetrics, PolicyExperimentOutput


class PolicyExperimentRunner:
    """Run one immutable Policy on one allowed benchmark split."""

    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        policy: VersionedPolicy,
        *,
        experiment_id: str,
        split: Literal["train", "validation"],
        repetitions: int,
        benchmark_root: Path = Path("benchmarks"),
    ) -> None:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        self.project_root = project_root.resolve()
        self.settings = settings
        self.policy = policy
        self.experiment_id = experiment_id
        self.split = split
        self.repetitions = repetitions
        resolved_benchmark_root = (
            benchmark_root
            if benchmark_root.is_absolute()
            else self.project_root / benchmark_root
        ).resolve()
        self.benchmark_root = resolved_benchmark_root.relative_to(self.project_root).as_posix()
        self.loader = BenchmarkLoader(resolved_benchmark_root)
        self.benchmark_manifest = self.loader.verify_manifest()
        self.runs_root = self.project_root / "runs" / experiment_id
        self.experiment_path = self.project_root / "evaluation_runs" / experiment_id
        self.agent_workspaces = WorkspaceManager(self.runs_root)
        self.evaluation_workspaces = WorkspaceManager(self.experiment_path / ".workspaces")

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

    def run(self) -> PolicyExperimentOutput:
        sandbox_digest = _sandbox_digest(self.settings.sandbox.image)
        evaluator = IndependentEvaluator(
            self.loader,
            self.evaluation_workspaces,
            self.settings.sandbox,
            trajectories_root=self.runs_root,
        )
        results = []
        trajectory_paths: dict[str, Path] = {}
        catalog_hash: str | None = None
        llm = LLMClient(self.settings.model)
        tasks = [task for task in self.loader.load_tasks() if task.split == self.split]
        for repetition in range(1, self.repetitions + 1):
            for task in tasks:
                run_id = f"run_{task.config.task_id}_r{repetition:02d}"
                run = self.loader.create_agent_workspace(
                    task, self.agent_workspaces, run_id=run_id
                )
                with MCPToolProvider(self._server(run.workspace_path, run.artifacts_path)) as tools:
                    current_catalog_hash = tool_catalog_hash(tools.list_tools())
                    if catalog_hash is None:
                        catalog_hash = current_catalog_hash
                    elif catalog_hash != current_catalog_hash:
                        raise RuntimeError("Tool catalog changed during Policy experiment")
                    recorder = TrajectoryRecorder(
                        run.run_path,
                        RunMetadata(
                            run_id=run_id,
                            task_id=task.config.task_id,
                            agent_release=__version__,
                            policy_version=self.policy.policy_id,
                            policy_hash=self.policy.content_hash,
                            experience_version="none",
                            experience_hash="none",
                            model=self.settings.model.model,
                            temperature=self.settings.model.temperature,
                            prompt_version="react-system-v1+policy-v1",
                            max_steps=self.policy.policy.max_react_steps,
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
                    ReActAgent(
                        llm=llm,
                        tool_provider=tools,
                        max_tool_retries=self.settings.agent.max_tool_retries,
                        max_context_chars=self.settings.agent.max_context_chars,
                        event_sink=recorder,
                        policy=self.policy.policy,
                    ).run(self.loader.to_task_spec(task, run.workspace_path))
                self.agent_workspaces.cleanup(run, redact=recorder.redactor.redact_text)
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
        if catalog_hash is None:
            raise RuntimeError(f"No benchmark tasks found for split: {self.split}")
        manifest = self._manifest(catalog_hash, sandbox_digest)
        summary = ExperimentReporter(self.experiment_path, manifest).summarize(
            results, trajectory_paths
        )
        return PolicyExperimentOutput(
            manifest=manifest,
            summary=summary,
            results=results,
            trajectory_paths={key: str(value) for key, value in trajectory_paths.items()},
        )

    def _manifest(self, catalog_hash: str, sandbox_digest: str) -> ExperimentManifest:
        return ExperimentManifest(
            experiment_id=self.experiment_id,
            experiment_version="policy-gate-v1",
            repetitions=self.repetitions,
            agent_release=__version__,
            policy_version=self.policy.policy_id,
            policy_hash=self.policy.content_hash,
            experience_version="none",
            experience_hash="none",
            model=self.settings.model.model,
            temperature=self.settings.model.temperature,
            prompt_version="react-system-v1+policy-v1",
            max_steps=self.policy.policy.max_react_steps,
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


def controlled_policy_conditions_match(
    champion: ExperimentManifest,
    candidate: ExperimentManifest,
) -> bool:
    allowed = {
        "created_at",
        "experiment_id",
        "policy_hash",
        "policy_version",
        "max_steps",
    }
    return champion.model_dump(exclude=allowed) == candidate.model_dump(exclude=allowed)


def arm_metrics(output: PolicyExperimentOutput) -> PolicyArmMetrics:
    task_resolutions = Counter(
        result.task_id for result in output.results if result.valid_evaluation and result.resolved
    )
    for result in output.results:
        task_resolutions.setdefault(result.task_id, 0)
    summary = output.summary
    return PolicyArmMetrics(
        policy_id=output.manifest.policy_version,
        total_attempts=summary.total_attempts,
        valid_attempts=summary.valid_evaluated_attempts,
        resolved_attempts=summary.resolved_attempts,
        resolution_rate=summary.resolution_rate,
        average_tokens=summary.average_tokens,
        average_react_steps=summary.average_react_steps,
        average_tool_calls=summary.average_tool_calls,
        average_latency_ms=summary.average_latency_ms,
        task_resolutions=dict(task_resolutions),
    )


def pairwise_experiment_ids(evolution_id: str, candidate_id: str) -> tuple[str, str]:
    """Return collision-free Champion and Candidate experiment IDs."""
    candidate_experiment_id = f"{evolution_id}-{candidate_id}"
    return f"{candidate_experiment_id}-champion", candidate_experiment_id


def run_pairwise_validation(
    project_root: Path,
    settings: AppSettings,
    champion: VersionedPolicy,
    candidate: VersionedPolicy,
    *,
    evolution_id: str,
    benchmark_root: Path = Path("benchmarks"),
) -> PairwiseGateReport:
    """Run the required nine attempts per arm, then persist a deterministic report."""
    repetitions = settings.evolution.validation_repetitions
    champion_experiment_id, candidate_experiment_id = pairwise_experiment_ids(
        evolution_id, candidate.policy_id
    )
    champion_output = PolicyExperimentRunner(
        project_root,
        settings,
        champion,
        experiment_id=champion_experiment_id,
        split="validation",
        repetitions=repetitions,
        benchmark_root=benchmark_root,
    ).run()
    candidate_output = PolicyExperimentRunner(
        project_root,
        settings,
        candidate,
        experiment_id=candidate_experiment_id,
        split="validation",
        repetitions=repetitions,
        benchmark_root=benchmark_root,
    ).run()
    report = compare_pairwise_validation(
        arm_metrics(champion_output),
        arm_metrics(candidate_output),
        candidate_id=candidate.policy_id,
        controlled_conditions_match=controlled_policy_conditions_match(
            champion_output.manifest, candidate_output.manifest
        ),
        significant_cost_reduction=settings.evolution.significant_cost_reduction,
    )
    report_path = (
        project_root.resolve()
        / "evolution_runs"
        / evolution_id
        / candidate.policy_id
        / "pairwise_report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
