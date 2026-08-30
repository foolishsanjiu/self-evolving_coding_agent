"""Fixed-policy ReAct baseline orchestration for the frozen benchmark."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from mcp import StdioServerParameters

from evodev import __version__
from evodev.agent import ReActAgent
from evodev.agent.react_agent import SYSTEM_PROMPT
from evodev.benchmark import BenchmarkLoader
from evodev.config import AppSettings, load_settings
from evodev.evaluation.evaluator import IndependentEvaluator
from evodev.evaluation.experiment import ExperimentReporter
from evodev.evaluation.models import (
    EvaluationRequest,
    ExperimentManifest,
    ExperimentSummary,
)
from evodev.llm import LLMClient
from evodev.sandbox import WorkspaceManager
from evodev.tools import MCPToolProvider
from evodev.trajectory import RunMetadata, TrajectoryRecorder, tool_catalog_hash


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sandbox_digest(image: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"Cannot inspect sandbox image: {image}")
    return completed.stdout.strip()


class FixedPolicyBaselineRunner:
    """Run one frozen ReAct configuration over every benchmark task."""

    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        experiment_id: str = "exp-baseline-v1",
        repetitions: int = 1,
    ) -> None:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        self.project_root = project_root.resolve()
        self.settings = settings
        self.experiment_id = experiment_id
        self.repetitions = repetitions
        self.loader = BenchmarkLoader(self.project_root / "benchmarks")
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

    def run(self) -> tuple[ExperimentManifest, ExperimentSummary]:
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
        for repetition in range(1, self.repetitions + 1):
            for task in self.loader.load_tasks():
                run_id = f"run_{task.config.task_id}_r{repetition:02d}"
                run = self.loader.create_agent_workspace(
                    task, self.agent_workspaces, run_id=run_id
                )
                with MCPToolProvider(self._server(run.workspace_path, run.artifacts_path)) as tools:
                    current_catalog_hash = tool_catalog_hash(tools.list_tools())
                    if catalog_hash is None:
                        catalog_hash = current_catalog_hash
                    elif catalog_hash != current_catalog_hash:
                        raise RuntimeError("Tool catalog changed during controlled baseline")
                    recorder = TrajectoryRecorder(
                        run.run_path,
                        RunMetadata(
                            run_id=run_id,
                            task_id=task.config.task_id,
                            agent_release=__version__,
                            policy_version="fixed-react-v1",
                            policy_hash=_sha256_text(SYSTEM_PROMPT),
                            experience_version="none",
                            experience_hash=_sha256_text("none"),
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
                    )
                    agent.run(self.loader.to_task_spec(task, run.workspace_path))
                self.agent_workspaces.cleanup(
                    run, redact=recorder.redactor.redact_text
                )
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
        manifest = ExperimentManifest(
            experiment_id=self.experiment_id,
            experiment_version="exp-baseline-v1",
            repetitions=self.repetitions,
            agent_release=__version__,
            policy_version="fixed-react-v1",
            policy_hash=_sha256_text(SYSTEM_PROMPT),
            experience_version="none",
            experience_hash=_sha256_text("none"),
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
        )
        summary = ExperimentReporter(self.experiment_path, manifest).summarize(
            results, trajectory_paths
        )
        return manifest, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen EvoDev baseline.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--experiment-id", default="exp-baseline-v1")
    parser.add_argument("--repetitions", type=int, default=1)
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve()
    settings = load_settings(project_root / "configs", project_root / ".env")
    _, summary = FixedPolicyBaselineRunner(
        project_root,
        settings,
        experiment_id=arguments.experiment_id,
        repetitions=arguments.repetitions,
    ).run()
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
