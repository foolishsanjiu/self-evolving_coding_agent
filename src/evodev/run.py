"""Paid one-task demo runner kept separate from controlled Final results."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from mcp import StdioServerParameters
from pydantic import BaseModel, ConfigDict

from evodev import __version__
from evodev.agent import ReActAgent
from evodev.benchmark import BenchmarkLoader, BenchmarkTask
from evodev.config import AppSettings, load_settings
from evodev.evaluation.baseline import _sandbox_digest
from evodev.evaluation.evaluator import IndependentEvaluator
from evodev.evaluation.models import EvaluationRequest, EvaluationResult
from evodev.experience import ExperienceRetriever, build_retrieval_query, load_snapshot
from evodev.llm import LLMClient
from evodev.policy.versioning import PolicyRepository
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash


class SingleTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    policy_version: str
    experience_version: str
    run_path: Path
    evaluation_path: Path
    evaluation: EvaluationResult


def require_single_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("Single Task execution requires --confirm-paid")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_task(loader: BenchmarkLoader, task_path: Path) -> BenchmarkTask:
    requested = task_path.resolve(strict=True)
    matches = [task for task in loader.load_tasks() if task.task_path == requested]
    if len(matches) != 1:
        raise ValueError("--task must identify one frozen Benchmark task directory")
    return matches[0]


class SingleTaskRunner:
    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        task_path: Path,
        policy_id: str,
        *,
        experience_snapshot: Path | None = None,
        run_id: str | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.settings = settings
        self.loader = BenchmarkLoader(self.project_root / "benchmarks")
        self.manifest = self.loader.verify_manifest()
        self.task = _resolve_task(self.loader, task_path)
        self.policy = PolicyRepository(self.project_root / "policies").load(policy_id)
        self.run_id = run_id or f"single-{self.task.config.task_id}-{policy_id}"
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.run_id) is None:
            raise ValueError("--run-id contains unsupported characters")

        self.experience_version = "none"
        self.experience_hash = _sha256_text("none")
        self.retriever: ExperienceRetriever | None = None
        if experience_snapshot is not None:
            snapshot = load_snapshot(experience_snapshot.resolve(strict=True))
            self.experience_version = snapshot.version
            self.experience_hash = snapshot.content_hash
            self.retriever = ExperienceRetriever(
                snapshot.experiences,
                snapshot.sources,
                top_k=settings.experience.top_k,
                max_chars=settings.experience.max_chars,
            )
        self.runs_root = self.project_root / "runs" / "single"
        self.evaluation_root = self.project_root / "evaluation_runs" / "single"

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

    def run(self) -> SingleTaskResult:
        run_path = self.runs_root / self.run_id
        evaluation_path = self.evaluation_root / self.run_id
        if run_path.exists() or evaluation_path.exists():
            raise FileExistsError("Single Task run ID already exists; choose a new --run-id")

        sandbox_digest = _sandbox_digest(self.settings.sandbox.image)
        workspaces = WorkspaceManager(self.runs_root)
        run = self.loader.create_agent_workspace(
            self.task,
            workspaces,
            run_id=self.run_id,
        )
        retrieval = (
            self.retriever.retrieve(build_retrieval_query(self.task))
            if self.retriever is not None
            else None
        )
        if retrieval is not None:
            (run.run_path / "retrieval.json").write_text(
                retrieval.model_dump_json(indent=2), encoding="utf-8"
            )
        with MCPToolProvider(self._server(run.workspace_path, run.artifacts_path)) as tools:
            catalog_hash = tool_catalog_hash(tools.list_tools())
            recorder = TrajectoryRecorder(
                run.run_path,
                RunMetadata(
                    run_id=self.run_id,
                    task_id=self.task.config.task_id,
                    agent_release=__version__,
                    policy_version=self.policy.policy_id,
                    policy_hash=self.policy.content_hash,
                    experience_version=self.experience_version,
                    experience_hash=self.experience_hash,
                    model=self.settings.model.model,
                    temperature=self.settings.model.temperature,
                    prompt_version=(
                        "react-system-v1+policy-v1"
                        + ("+experience-v1" if retrieval is not None else "")
                    ),
                    max_steps=self.policy.policy.max_react_steps,
                    context_budget=self.settings.agent.max_context_chars,
                    tool_provider="mcp-devtools-v1",
                    tool_catalog_hash=catalog_hash,
                    benchmark_version=self.manifest.benchmark_version,
                    benchmark_hash=self.manifest.manifest_hash,
                    sandbox_image=self.settings.sandbox.image,
                    sandbox_digest=sandbox_digest,
                ),
                env_file=self.project_root / ".env",
            )
            ReActAgent(
                llm=LLMClient(self.settings.model),
                tool_provider=tools,
                max_tool_retries=self.settings.agent.max_tool_retries,
                max_context_chars=self.settings.agent.max_context_chars,
                event_sink=recorder,
                experience_section=retrieval.prompt_section if retrieval else "",
                policy=self.policy.policy,
            ).run(self.loader.to_task_spec(self.task, run.workspace_path))
        workspaces.cleanup(run, redact=recorder.redactor.redact_text)

        evaluator = IndependentEvaluator(
            self.loader,
            WorkspaceManager(self.evaluation_root / ".workspaces"),
            self.settings.sandbox,
            trajectories_root=self.runs_root,
        )
        evaluation = evaluator.evaluate(
            EvaluationRequest(
                task_id=self.task.config.task_id,
                final_patch=(run.run_path / "final.patch").read_text(encoding="utf-8"),
                agent_run_id=self.run_id,
            ),
            evaluation_path,
        )
        return SingleTaskResult(
            run_id=self.run_id,
            task_id=self.task.config.task_id,
            policy_version=self.policy.policy_id,
            experience_version=self.experience_version,
            run_path=run.run_path,
            evaluation_path=evaluation_path,
            evaluation=evaluation,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one paid EvoDev Benchmark task.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--experience-snapshot", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--confirm-paid", action="store_true")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    require_single_paid_confirmation(arguments.confirm_paid)
    root = arguments.project_root.resolve()
    task_path = arguments.task
    if not task_path.is_absolute():
        task_path = root / task_path
    snapshot_path = arguments.experience_snapshot
    if snapshot_path is not None and not snapshot_path.is_absolute():
        snapshot_path = root / snapshot_path
    settings = load_settings(root / "configs", root / ".env")
    result = SingleTaskRunner(
        root,
        settings,
        task_path,
        arguments.policy,
        experience_snapshot=snapshot_path,
        run_id=arguments.run_id,
    ).run()
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
