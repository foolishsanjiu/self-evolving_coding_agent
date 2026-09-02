"""Frozen Task 14 experiment planning and result contracts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter
from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import Literal

import yaml
from mcp import StdioServerParameters
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evodev import __version__
from evodev.benchmark import BenchmarkLoader
from evodev.config import AppSettings, load_settings
from evodev.evaluation.baseline import _sandbox_digest
from evodev.evaluation.models import EVALUATOR_VERSION, FailureType
from evodev.experience import load_snapshot
from evodev.policy.versioning import PolicyRepository
from evodev.tools import MCPToolProvider
from evodev.trajectory import tool_catalog_hash
from evodev.trajectory.models import utc_now


class FinalVariantId(StrEnum):
    BASELINE = "A"
    EXPERIENCE = "B"
    POLICY = "C"
    COMBINED = "D"


class FinalVariantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: FinalVariantId
    label: str = Field(min_length=1)
    experience_enabled: bool
    evolved_policy_enabled: bool


class FinalExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    experiment_version: str = Field(min_length=1)
    results_dir: str = Field(min_length=1)
    benchmark_root: str = "benchmarks"
    benchmark_split: Literal["test"] = "test"
    runs_per_task_per_variant: Literal[3] = 3
    baseline_policy_id: str = Field(pattern=r"^policy-v[0-9]{3}$")
    champion_policy_id: str = Field(pattern=r"^policy-v[0-9]{3}$")
    experience_snapshot: str = Field(min_length=1)
    minimum_accepted_case_studies: Literal[2] = 2
    variants: list[FinalVariantConfig] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_controlled_matrix(self) -> FinalExperimentConfig:
        if self.baseline_policy_id == self.champion_policy_id:
            raise ValueError("Baseline and Champion Policy must be distinct")
        expected = {
            FinalVariantId.BASELINE: (False, False),
            FinalVariantId.EXPERIENCE: (True, False),
            FinalVariantId.POLICY: (False, True),
            FinalVariantId.COMBINED: (True, True),
        }
        observed = {
            item.variant_id: (
                item.experience_enabled,
                item.evolved_policy_enabled,
            )
            for item in self.variants
        }
        if observed != expected or len(observed) != len(self.variants):
            raise ValueError("Final variants must be the exact A/B/C/D 2x2 matrix")
        for value in (self.results_dir, self.benchmark_root, self.experience_snapshot):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Final experiment paths must be project-relative")
        return self


class FinalFreezeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code_read_only: Literal[True] = True
    benchmark_read_only: Literal[True] = True
    experience_snapshot_read_only: Literal[True] = True
    policy_snapshot_read_only: Literal[True] = True
    sandbox_read_only: Literal[True] = True
    experience_generation_enabled: Literal[False] = False
    policy_evolution_enabled: Literal[False] = False
    selective_reruns_allowed: Literal[False] = False


class FinalVariantManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: FinalVariantId
    label: str
    experience_enabled: bool
    evolved_policy_enabled: bool
    policy_version: str
    policy_hash: str
    experience_version: str
    experience_hash: str
    prompt_version: str
    max_steps: int = Field(gt=0)
    context_budget: int = Field(gt=0)
    runs_per_task: Literal[3] = 3
    expected_attempts: int = Field(gt=0)


class FinalExperimentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    experiment_version: str
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    agent_release: str
    model_provider: str
    model: str
    temperature: float = Field(ge=0, le=2)
    benchmark_version: str
    benchmark_hash: str
    benchmark_root: str = "benchmarks"
    benchmark_split: Literal["test"] = "test"
    benchmark_task_ids: list[str] = Field(min_length=1)
    sandbox_image: str
    sandbox_digest: str
    evaluator_version: str
    tool_provider: Literal["mcp-devtools-v1"] = "mcp-devtools-v1"
    tool_catalog_version: Literal["mcp-devtools-v1"] = "mcp-devtools-v1"
    tool_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variants: list[FinalVariantManifest] = Field(min_length=4, max_length=4)
    freeze: FinalFreezeContract = Field(default_factory=FinalFreezeContract)
    created_at: str = Field(default_factory=utc_now)


class FinalRuntimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_clean: bool
    sandbox_digest: str = Field(min_length=1)
    tool_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinalExperimentPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: FinalExperimentManifest
    ready_to_freeze: bool
    blocking_reasons: list[str]
    accepted_case_studies: int = Field(ge=0)
    required_accepted_case_studies: int = Field(ge=1)
    expected_agent_runs: int = Field(gt=0)


class FinalRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: FinalVariantId
    task_id: str
    agent_run_id: str
    resolved: bool
    valid_evaluation: bool
    failure_type: FailureType
    react_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    searched_before_edit: bool
    inspected_tests_before_edit: bool
    patch_attempts: int = Field(ge=0)


class FinalRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: FinalVariantId
    task_id: str
    repetition: Literal[1, 2, 3]
    agent_run_id: str


class FinalEfficiencyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    average_react_steps: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_tokens: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)


class FinalVariantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: FinalVariantId
    label: str
    policy_version: str
    total_attempts: int = Field(ge=0)
    valid_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    resolution_rate: float = Field(ge=0, le=1)
    overall_efficiency: FinalEfficiencyMetrics
    resolved_run_efficiency: FinalEfficiencyMetrics
    search_before_edit_rate: float = Field(ge=0, le=1)
    test_inspection_before_edit_rate: float = Field(ge=0, le=1)
    average_patch_attempts: float = Field(ge=0)
    failure_distribution: dict[FailureType, int]


class FinalExperimentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    variants: list[FinalVariantSummary] = Field(min_length=4, max_length=4)
    created_at: str = Field(default_factory=utc_now)


class FinalRunResultsArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    results: list[FinalRunResult] = Field(min_length=1)
    created_at: str = Field(default_factory=utc_now)


def load_final_experiment_config(path: Path) -> FinalExperimentConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Final experiment config must contain a YAML mapping")
    return FinalExperimentConfig.model_validate(data)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Git identity check failed")
    return completed.stdout.strip()


def collect_final_runtime_identity(
    project_root: Path,
    settings: AppSettings,
) -> FinalRuntimeIdentity:
    root = project_root.resolve()
    fixture = root / "fixtures" / "simple_read"
    server = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "mcp_servers.devtools.server",
            "--workspace",
            str(fixture),
            "--sandbox-config",
            str(root / "configs" / "sandbox.yaml"),
        ],
        cwd=str(root),
    )
    with MCPToolProvider(server) as provider:
        catalog_hash = tool_catalog_hash(provider.list_tools())
    return FinalRuntimeIdentity(
        git_commit=_git(root, "rev-parse", "HEAD"),
        git_clean=not bool(_git(root, "status", "--porcelain")),
        sandbox_digest=_sandbox_digest(settings.sandbox.image),
        tool_catalog_hash=catalog_hash,
    )


class FinalExperimentPlanner:
    def __init__(
        self,
        project_root: Path,
        settings: AppSettings,
        config: FinalExperimentConfig,
    ) -> None:
        self.project_root = project_root.resolve()
        self.settings = settings
        self.config = config
        self.loader = BenchmarkLoader(self.project_root / config.benchmark_root)
        self.benchmark_manifest = self.loader.verify_manifest()
        self.repository = PolicyRepository(self.project_root / "policies")
        self.snapshot = load_snapshot(self.project_root / config.experience_snapshot)

    def preflight(self, identity: FinalRuntimeIdentity) -> FinalExperimentPreflight:
        tasks = self.loader.load_tasks()
        test_tasks = sorted(
            task.config.task_id
            for task in tasks
            if task.split == "test"
        )
        task_splits = {task.config.task_id: task.split for task in tasks}
        baseline = self.repository.load(self.config.baseline_policy_id)
        champion = self.repository.load(self.config.champion_policy_id)
        blockers = []
        if self.repository.champion().policy_id != champion.policy_id:
            blockers.append("Configured Champion does not match policies/index.json")
        if not test_tasks:
            blockers.append("Final benchmark must contain at least one Test task")
        if any(
            task_splits.get(source.task_id) != "train"
            for source in self.snapshot.sources
        ):
            blockers.append("Experience snapshot contains non-Train provenance")
        accepted = sum(
            self.repository.load(path.stem).status == "accepted"
            for path in self.repository.root.glob("candidate-[0-9][0-9][0-9].yaml")
        )
        if accepted < self.config.minimum_accepted_case_studies:
            blockers.append(
                "Task 14 requires at least two Accepted Mutation case studies"
            )
        if not identity.git_clean:
            blockers.append("Git working tree is not clean")

        variants = []
        for item in self.config.variants:
            policy = champion if item.evolved_policy_enabled else baseline
            variants.append(
                FinalVariantManifest(
                    variant_id=item.variant_id,
                    label=item.label,
                    experience_enabled=item.experience_enabled,
                    evolved_policy_enabled=item.evolved_policy_enabled,
                    policy_version=policy.policy_id,
                    policy_hash=policy.content_hash,
                    experience_version=(
                        self.snapshot.version if item.experience_enabled else "none"
                    ),
                    experience_hash=(
                        self.snapshot.content_hash
                        if item.experience_enabled
                        else _sha256_text("none")
                    ),
                    prompt_version=self._prompt_version(item),
                    max_steps=policy.policy.max_react_steps,
                    context_budget=self.settings.agent.max_context_chars,
                    expected_attempts=(
                        len(test_tasks) * self.config.runs_per_task_per_variant
                    ),
                )
            )
        manifest = FinalExperimentManifest(
            experiment_id=self.config.experiment_id,
            experiment_version=self.config.experiment_version,
            git_commit=identity.git_commit,
            agent_release=__version__,
            model_provider=self.settings.model.provider,
            model=self.settings.model.model,
            temperature=self.settings.model.temperature,
            benchmark_version=self.benchmark_manifest.benchmark_version,
            benchmark_hash=self.benchmark_manifest.manifest_hash,
            benchmark_root=self.config.benchmark_root,
            benchmark_task_ids=test_tasks,
            sandbox_image=self.settings.sandbox.image,
            sandbox_digest=identity.sandbox_digest,
            evaluator_version=EVALUATOR_VERSION,
            tool_catalog_hash=identity.tool_catalog_hash,
            variants=variants,
        )
        return FinalExperimentPreflight(
            manifest=manifest,
            ready_to_freeze=not blockers,
            blocking_reasons=blockers,
            accepted_case_studies=accepted,
            required_accepted_case_studies=(
                self.config.minimum_accepted_case_studies
            ),
            expected_agent_runs=sum(item.expected_attempts for item in variants),
        )

    @staticmethod
    def _prompt_version(item: FinalVariantConfig) -> str:
        suffixes = []
        if item.experience_enabled:
            suffixes.append("experience-v1")
        if item.evolved_policy_enabled:
            suffixes.append("policy-v1")
        return "+".join(["react-system-v1", *suffixes])


def write_frozen_final_manifest(
    preflight: FinalExperimentPreflight,
    path: Path,
) -> FinalExperimentManifest:
    if not preflight.ready_to_freeze:
        raise RuntimeError("Final experiment is not ready to freeze")
    if path.exists():
        stored = FinalExperimentManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if stored.model_dump(exclude={"created_at"}) != preflight.manifest.model_dump(
            exclude={"created_at"}
        ):
            raise ValueError("Final experiment manifest is frozen with other conditions")
        return stored
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(preflight.manifest.model_dump_json(indent=2), encoding="utf-8")
    return preflight.manifest


def _mean(records: list[FinalRunResult], field: str) -> float:
    return round(fmean(getattr(item, field) for item in records), 4) if records else 0.0


def _efficiency(records: list[FinalRunResult]) -> FinalEfficiencyMetrics:
    return FinalEfficiencyMetrics(
        average_react_steps=_mean(records, "react_steps"),
        average_tool_calls=_mean(records, "tool_calls"),
        average_tokens=_mean(records, "tokens"),
        average_latency_ms=_mean(records, "latency_ms"),
    )


def build_final_run_plan(manifest: FinalExperimentManifest) -> list[FinalRunSpec]:
    return [
        FinalRunSpec(
            variant_id=variant.variant_id,
            task_id=task_id,
            repetition=repetition,
            agent_run_id=(
                f"{manifest.experiment_id}-{variant.variant_id.value}-"
                f"{task_id}-r{repetition:02d}"
            ),
        )
        for variant in manifest.variants
        for task_id in manifest.benchmark_task_ids
        for repetition in range(1, variant.runs_per_task + 1)
    ]


def summarize_final_results(
    manifest: FinalExperimentManifest,
    results: list[FinalRunResult],
) -> FinalExperimentSummary:
    if len({item.agent_run_id for item in results}) != len(results):
        raise ValueError("Final Agent run IDs must be unique")
    summaries = []
    for variant in manifest.variants:
        records = [item for item in results if item.variant_id == variant.variant_id]
        if len(records) != variant.expected_attempts:
            raise ValueError(f"Incomplete Final results for Variant {variant.variant_id}")
        counts = Counter(item.task_id for item in records)
        if set(counts) != set(manifest.benchmark_task_ids) or any(
            count != variant.runs_per_task for count in counts.values()
        ):
            raise ValueError(f"Unbalanced Test repetitions for Variant {variant.variant_id}")
        valid = [item for item in records if item.valid_evaluation]
        resolved = [item for item in valid if item.resolved]
        summaries.append(
            FinalVariantSummary(
                variant_id=variant.variant_id,
                label=variant.label,
                policy_version=variant.policy_version,
                total_attempts=len(records),
                valid_attempts=len(valid),
                resolved_attempts=len(resolved),
                resolution_rate=(round(len(resolved) / len(valid), 4) if valid else 0),
                overall_efficiency=_efficiency(records),
                resolved_run_efficiency=_efficiency(resolved),
                search_before_edit_rate=_mean(records, "searched_before_edit"),
                test_inspection_before_edit_rate=_mean(
                    records, "inspected_tests_before_edit"
                ),
                average_patch_attempts=_mean(records, "patch_attempts"),
                failure_distribution=dict(Counter(item.failure_type for item in records)),
            )
        )
    if {item.variant_id for item in results} != {
        item.variant_id for item in manifest.variants
    }:
        raise ValueError("Final results contain an unknown Variant")
    return FinalExperimentSummary(
        experiment_id=manifest.experiment_id,
        variants=summaries,
    )


def _parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Plan, freeze, run, and present EvoDev Task 14."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments/final-v1.yaml"),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="Run a no-cost Final Experiment preflight.")
    freeze = commands.add_parser("freeze", help="Write the immutable Final Manifest.")
    freeze.add_argument("--confirm-freeze", action="store_true")
    run = commands.add_parser("run", help="Execute the paid frozen Final experiment.")
    run.add_argument("--confirm-paid", action="store_true")
    demo = commands.add_parser("demo", help="Render an existing run as concise CLI logs.")
    demo.add_argument("--run-path", type=Path, required=True)
    demo.add_argument("--evaluation-report", type=Path, required=True)
    verify = commands.add_parser(
        "verify", help="Verify persisted Final artifacts without external calls."
    )
    verify.add_argument("--results-dir", type=Path)
    figures = commands.add_parser(
        "figures", help="Generate immutable PNG figures from summary.json."
    )
    figures.add_argument("--results-dir", type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    root = arguments.project_root.resolve()
    if arguments.command == "demo":
        from evodev.evaluation.demo import render_cli_demo

        print("\n".join(render_cli_demo(arguments.run_path, arguments.evaluation_report)))
        return
    if arguments.command in {"verify", "figures"}:
        config_path = arguments.config
        if not config_path.is_absolute():
            config_path = root / config_path
        config = load_final_experiment_config(config_path)
        results_dir = arguments.results_dir or Path(config.results_dir)
        if not results_dir.is_absolute():
            results_dir = root / results_dir
        if arguments.command == "figures":
            from evodev.evaluation.final_figures import generate_final_figures

            report = generate_final_figures(results_dir)
        else:
            from evodev.evaluation.final_artifacts import verify_final_result_artifacts

            report = verify_final_result_artifacts(results_dir)
        print(report.model_dump_json(indent=2))
        return
    if arguments.command == "run":
        from evodev.evaluation.final_runner import require_final_paid_confirmation

        require_final_paid_confirmation(arguments.confirm_paid)
    config_path = arguments.config
    if not config_path.is_absolute():
        config_path = root / config_path
    config = load_final_experiment_config(config_path)
    settings = load_settings(root / "configs", root / ".env")
    planner = FinalExperimentPlanner(root, settings, config)
    preflight = planner.preflight(collect_final_runtime_identity(root, settings))
    if arguments.command == "freeze":
        if not arguments.confirm_freeze:
            raise PermissionError("Final Manifest freeze requires --confirm-freeze")
        manifest = write_frozen_final_manifest(
            preflight,
            root / config.results_dir / "experiment_manifest.json",
        )
        print(manifest.model_dump_json(indent=2))
        return
    if arguments.command == "run":
        from evodev.evaluation.final_runner import FinalExperimentRunner

        manifest_path = root / config.results_dir / "experiment_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("Frozen Final Manifest is missing")
        manifest = FinalExperimentManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        summary = FinalExperimentRunner(
            root,
            settings,
            config,
            manifest,
            preflight,
        ).run()
        print(summary.model_dump_json(indent=2))
        return
    print(preflight.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
