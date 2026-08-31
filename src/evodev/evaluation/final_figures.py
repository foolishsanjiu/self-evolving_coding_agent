"""Deterministic Task 14 figures generated only from summary.json."""

from __future__ import annotations

import hashlib
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evodev.evaluation.final_experiment import FinalExperimentSummary, FinalVariantId

FIGURE_GENERATOR_VERSION = "1.0"
FIGURE_NAMES = (
    "resolution_rate.png",
    "efficiency.png",
    "behavior_change.png",
    "policy_generation.png",
)
_COLORS = {
    FinalVariantId.BASELINE: "#64748b",
    FinalVariantId.EXPERIENCE: "#0ea5e9",
    FinalVariantId.POLICY: "#8b5cf6",
    FinalVariantId.COMBINED: "#10b981",
}


class FinalFigureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    generator_version: Literal["1.0"] = FIGURE_GENERATOR_VERSION
    source: Literal["summary.json"] = "summary.json"
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    figures: dict[str, str]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return plt


def _labels(summary: FinalExperimentSummary) -> list[str]:
    return [f"{item.variant_id.value}. {item.label}" for item in summary.variants]


def _finish(figure, path: Path, summary_hash: str) -> None:
    figure.savefig(
        path,
        dpi=160,
        bbox_inches="tight",
        metadata={
            "Software": f"EvoDev Final Figure Generator {FIGURE_GENERATOR_VERSION}",
            "Description": f"Generated from summary.json sha256:{summary_hash}",
        },
    )
    _matplotlib().close(figure)


def _resolution_rate(summary: FinalExperimentSummary, path: Path, source_hash: str) -> None:
    plt = _matplotlib()
    figure, axis = plt.subplots(figsize=(8, 4.8))
    values = [item.resolution_rate * 100 for item in summary.variants]
    bars = axis.bar(
        _labels(summary),
        values,
        color=[_COLORS[item.variant_id] for item in summary.variants],
    )
    axis.bar_label(bars, fmt="%.1f%%", padding=3)
    axis.set(title="Task Resolution Rate", ylabel="Resolved valid runs (%)", ylim=(0, 110))
    axis.grid(axis="y", alpha=0.25)
    _finish(figure, path, source_hash)


def _efficiency(summary: FinalExperimentSummary, path: Path, source_hash: str) -> None:
    plt = _matplotlib()
    figure, axes = plt.subplots(2, 2, figsize=(11, 7.5))
    metrics = (
        ("average_react_steps", "ReAct steps"),
        ("average_tool_calls", "Tool calls"),
        ("average_tokens", "Tokens"),
        ("average_latency_ms", "Latency (ms)"),
    )
    labels = [item.variant_id.value for item in summary.variants]
    positions = list(range(len(labels)))
    width = 0.36
    for axis, (field, title) in zip(axes.flat, metrics, strict=True):
        overall = [getattr(item.overall_efficiency, field) for item in summary.variants]
        resolved = [
            getattr(item.resolved_run_efficiency, field) for item in summary.variants
        ]
        axis.bar([x - width / 2 for x in positions], overall, width, label="Overall")
        axis.bar([x + width / 2 for x in positions], resolved, width, label="Resolved runs")
        axis.set(title=title, xticks=positions, xticklabels=labels)
        axis.grid(axis="y", alpha=0.25)
    axes[0, 0].legend()
    figure.suptitle("Efficiency by Variant (Overall vs Resolved Runs)")
    figure.tight_layout()
    _finish(figure, path, source_hash)


def _behavior_change(summary: FinalExperimentSummary, path: Path, source_hash: str) -> None:
    plt = _matplotlib()
    figure, axis = plt.subplots(figsize=(9.5, 5.2))
    labels = [item.variant_id.value for item in summary.variants]
    positions = list(range(len(labels)))
    width = 0.34
    search = [item.search_before_edit_rate * 100 for item in summary.variants]
    inspect = [item.test_inspection_before_edit_rate * 100 for item in summary.variants]
    axis.bar([x - width / 2 for x in positions], search, width, label="Search before edit")
    axis.bar([x + width / 2 for x in positions], inspect, width, label="Inspect tests before edit")
    axis.set(
        title="Behavior Change by Variant",
        ylabel="Behavior rate (%)",
        xticks=positions,
        xticklabels=labels,
        ylim=(0, 105),
    )
    axis.grid(axis="y", alpha=0.25)
    patch_axis = axis.twinx()
    patch_axis.plot(
        positions,
        [item.average_patch_attempts for item in summary.variants],
        color="#f97316",
        marker="o",
        linewidth=2,
        label="Average patch attempts",
    )
    patch_axis.set_ylabel("Average patch attempts")
    handles, legend_labels = axis.get_legend_handles_labels()
    extra_handles, extra_labels = patch_axis.get_legend_handles_labels()
    axis.legend(
        handles + extra_handles,
        legend_labels + extra_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.13),
        ncol=3,
    )
    _finish(figure, path, source_hash)


def _policy_generation(summary: FinalExperimentSummary, path: Path, source_hash: str) -> None:
    plt = _matplotlib()
    by_id = {item.variant_id: item for item in summary.variants}
    baseline = by_id[FinalVariantId.BASELINE]
    policy = by_id[FinalVariantId.POLICY]
    if baseline.policy_version == policy.policy_version:
        raise ValueError("Policy generation figure requires distinct baseline and evolved policies")
    figure, axis = plt.subplots(figsize=(7.5, 4.8))
    values = [baseline.resolution_rate * 100, policy.resolution_rate * 100]
    bars = axis.bar(
        [baseline.policy_version, policy.policy_version],
        values,
        color=[_COLORS[FinalVariantId.BASELINE], _COLORS[FinalVariantId.POLICY]],
    )
    axis.bar_label(bars, fmt="%.1f%%", padding=3)
    axis.plot([0, 1], values, color="#334155", marker="o", linewidth=1.5)
    axis.set(
        title="Policy-only Resolution Across Accepted Generations",
        ylabel="Resolved valid runs (%)",
        ylim=(0, 110),
    )
    axis.text(
        0.5,
        0.98,
        "Experience disabled in both variants",
        transform=axis.transAxes,
        ha="center",
        va="top",
        color="#475569",
    )
    axis.grid(axis="y", alpha=0.25)
    _finish(figure, path, source_hash)


def generate_final_figures(results_root: Path) -> FinalFigureManifest:
    root = results_root.resolve(strict=True)
    summary_path = root / "summary.json"
    summary = FinalExperimentSummary.model_validate_json(
        summary_path.read_text(encoding="utf-8")
    )
    figures_path = root / "figures"
    temporary_path = root / ".figures.tmp"
    if figures_path.exists() or temporary_path.exists():
        raise FileExistsError("Final figures already exist or a previous generation is incomplete")
    source_hash = _sha256(summary_path)
    temporary_path.mkdir()
    try:
        _resolution_rate(summary, temporary_path / FIGURE_NAMES[0], source_hash)
        _efficiency(summary, temporary_path / FIGURE_NAMES[1], source_hash)
        _behavior_change(summary, temporary_path / FIGURE_NAMES[2], source_hash)
        _policy_generation(summary, temporary_path / FIGURE_NAMES[3], source_hash)
        manifest = FinalFigureManifest(
            experiment_id=summary.experiment_id,
            summary_sha256=source_hash,
            figures={name: _sha256(temporary_path / name) for name in FIGURE_NAMES},
        )
        (temporary_path / "figure_manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        temporary_path.replace(figures_path)
        return manifest
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise


def verify_final_figures(results_root: Path) -> FinalFigureManifest:
    root = results_root.resolve(strict=True)
    figures_path = root / "figures"
    manifest = FinalFigureManifest.model_validate_json(
        (figures_path / "figure_manifest.json").read_text(encoding="utf-8")
    )
    if manifest.summary_sha256 != _sha256(root / "summary.json"):
        raise ValueError("Final figures were not generated from the current summary.json")
    if set(manifest.figures) != set(FIGURE_NAMES):
        raise ValueError("Final figure manifest has an unexpected file set")
    for name in FIGURE_NAMES:
        if manifest.figures[name] != _sha256(figures_path / name):
            raise ValueError(f"Final figure hash does not match: {name}")
    return manifest
