"""Paid A/B/C/D execution over one frozen Task 14 Manifest."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import StdioServerParameters

from evodev.agent import ReActAgent
from evodev.benchmark import BenchmarkLoader
from evodev.config import AppSettings
from evodev.evaluation.evaluator import IndependentEvaluator
from evodev.evaluation.experiment import TrajectoryMetricReader
from evodev.evaluation.final_artifacts import write_final_result_artifacts
from evodev.evaluation.final_experiment import (
    FinalExperimentConfig,
    FinalExperimentManifest,
    FinalExperimentPreflight,
    FinalExperimentSummary,
    FinalRunResult,
    FinalRunSpec,
    build_final_run_plan,
)
from evodev.evaluation.final_figures import generate_final_figures
from evodev.evaluation.models import EvaluationRequest
from evodev.experience import ExperienceRetriever, build_retrieval_query, load_snapshot
from evodev.llm import LLMClient
from evodev.policy.models import VersionedPolicy
from evodev.policy.versioning import PolicyRepository
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash


def require_final_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("Final Experiment requires --confirm-paid")


class FinalExperimentRunner:
    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        config: FinalExperimentConfig,
        manifest: FinalExperimentManifest,
        preflight: FinalExperimentPreflight,
    ) -> None:
        self.project_root = project_root.resolve()
        self.settings = settings
        self.config = config
        self.manifest = manifest
        self.preflight = preflight
        if not preflight.ready_to_freeze:
            raise RuntimeError("Final Experiment Preflight is not ready")
        if manifest.model_dump(exclude={"created_at"}) != preflight.manifest.model_dump(
            exclude={"created_at"}
        ):
            raise ValueError("Runtime conditions do not match the frozen Final Manifest")

        self.results_root = self.project_root / config.results_dir
        self.runs_root = self.project_root / "runs" / config.experiment_id
        self.loader = BenchmarkLoader(self.project_root / config.benchmark_root)
        self.repository = PolicyRepository(self.project_root / "policies")
        snapshot = load_snapshot(self.project_root / config.experience_snapshot)
        self.retriever = ExperienceRetriever(
            snapshot.experiences,
            snapshot.sources,
            top_k=settings.experience.top_k,
            max_chars=settings.experience.max_chars,
        )
        self.variants = {item.variant_id: item for item in manifest.variants}
        self.tasks = {
            task.config.task_id: task
            for task in self.loader.load_tasks()
            if task.split == "test"
        }
        self.plan = build_final_run_plan(manifest)
        expected_runs = sum(item.expected_attempts for item in manifest.variants)
        if len(self.plan) != expected_runs:
            raise ValueError("Final Experiment run plan does not match the frozen Manifest")

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

    def _assert_fresh_execution(self) -> None:
        occupied = [
            self.results_root / "instances",
            self.results_root / "run_results.json",
            self.results_root / "summary.json",
            self.results_root / "summary.csv",
        ]
        if any(path.exists() for path in occupied):
            raise FileExistsError(
                "Final execution artifacts already exist; use a new Experiment Version"
            )
        if self.runs_root.exists() and any(self.runs_root.iterdir()):
            raise FileExistsError(
                "Final trajectories already exist; use a new Experiment Version"
            )

    def _policy(self, spec: FinalRunSpec) -> VersionedPolicy:
        variant = self.variants[spec.variant_id]
        policy = self.repository.load(variant.policy_version)
        if policy.content_hash != variant.policy_hash:
            raise ValueError(f"Policy Hash changed for Variant {spec.variant_id}")
        return policy

    def run(self) -> FinalExperimentSummary:
        self._assert_fresh_execution()
        agent_workspaces = WorkspaceManager(self.runs_root)
        evaluation_workspaces = WorkspaceManager(
            self.project_root
            / "evaluation_runs"
            / self.config.experiment_id
            / ".workspaces"
        )
        evaluator = IndependentEvaluator(
            self.loader,
            evaluation_workspaces,
            self.settings.sandbox,
            trajectories_root=self.runs_root,
        )
        llm = LLMClient(self.settings.model)
        results = []
        for spec in self.plan:
            results.append(
                self._run_one(
                    spec,
                    llm,
                    evaluator,
                    agent_workspaces,
                )
            )
        summary = write_final_result_artifacts(self.results_root, self.manifest, results)
        generate_final_figures(self.results_root)
        return summary

    def _run_one(
        self,
        spec: FinalRunSpec,
        llm: LLMClient,
        evaluator: IndependentEvaluator,
        workspaces: WorkspaceManager,
    ) -> FinalRunResult:
        variant = self.variants[spec.variant_id]
        task = self.tasks[spec.task_id]
        policy = self._policy(spec)
        retrieval = self.retriever.retrieve(
            build_retrieval_query(task),
            "relevant" if variant.experience_enabled else "disabled",
        )
        run = self.loader.create_agent_workspace(
            task,
            workspaces,
            run_id=spec.agent_run_id,
        )
        (run.run_path / "retrieval.json").write_text(
            retrieval.model_dump_json(indent=2), encoding="utf-8"
        )
        with MCPToolProvider(self._server(run.workspace_path, run.artifacts_path)) as tools:
            current_catalog_hash = tool_catalog_hash(tools.list_tools())
            if current_catalog_hash != self.manifest.tool_catalog_hash:
                raise RuntimeError("MCP Tool Catalog changed after Final freeze")
            recorder = TrajectoryRecorder(
                run.run_path,
                RunMetadata(
                    run_id=spec.agent_run_id,
                    task_id=spec.task_id,
                    agent_release=self.manifest.agent_release,
                    policy_version=variant.policy_version,
                    policy_hash=variant.policy_hash,
                    experience_version=variant.experience_version,
                    experience_hash=variant.experience_hash,
                    model=self.manifest.model,
                    temperature=self.manifest.temperature,
                    prompt_version=variant.prompt_version,
                    max_steps=variant.max_steps,
                    context_budget=variant.context_budget,
                    tool_provider=self.manifest.tool_provider,
                    tool_catalog_hash=current_catalog_hash,
                    benchmark_version=self.manifest.benchmark_version,
                    benchmark_hash=self.manifest.benchmark_hash,
                    sandbox_image=self.manifest.sandbox_image,
                    sandbox_digest=self.manifest.sandbox_digest,
                ),
                env_file=self.project_root / ".env",
            )
            ReActAgent(
                llm=llm,
                tool_provider=tools,
                max_tool_retries=self.settings.agent.max_tool_retries,
                max_context_chars=variant.context_budget,
                event_sink=recorder,
                experience_section=retrieval.prompt_section,
                policy=policy.policy,
            ).run(self.loader.to_task_spec(task, run.workspace_path))
        workspaces.cleanup(run, redact=recorder.redactor.redact_text)
        instance = (
            self.results_root
            / "instances"
            / spec.variant_id.value
            / spec.task_id
            / f"attempt_{spec.repetition:02d}"
        )
        evaluation = evaluator.evaluate(
            EvaluationRequest(
                task_id=spec.task_id,
                final_patch=(run.run_path / "final.patch").read_text(encoding="utf-8"),
                agent_run_id=spec.agent_run_id,
            ),
            instance,
        )
        metrics = TrajectoryMetricReader.read(run.run_path)
        return FinalRunResult(
            variant_id=spec.variant_id,
            task_id=spec.task_id,
            agent_run_id=spec.agent_run_id,
            resolved=evaluation.resolved,
            valid_evaluation=evaluation.valid_evaluation,
            failure_type=evaluation.failure_type,
            react_steps=metrics.react_steps,
            tool_calls=metrics.tool_calls,
            tokens=metrics.tokens,
            latency_ms=metrics.latency_ms,
            searched_before_edit=metrics.searched_before_edit,
            inspected_tests_before_edit=metrics.inspected_tests_before_edit,
            patch_attempts=metrics.patch_attempts,
        )
