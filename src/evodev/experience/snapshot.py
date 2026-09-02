"""Canonical, immutable JSON snapshot for formal experience experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evodev.experience.models import (
    ExperienceExecutionContract,
    ExperienceSnapshot,
    ExperienceSource,
    StoredExperience,
)


def _canonical_hash(experiences: list[StoredExperience], sources: list[ExperienceSource]) -> str:
    payload = {
        "experiences": [item.model_dump(mode="json", exclude_none=True) for item in experiences],
        "sources": [item.model_dump(mode="json") for item in sources],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_snapshot(
    version: str,
    experiences: list[StoredExperience],
    sources: list[ExperienceSource],
) -> ExperienceSnapshot:
    active = sorted(
        (item for item in experiences if item.status.value == "active"),
        key=lambda item: item.experience_id,
    )
    active_ids = {item.experience_id for item in active}
    linked_sources = sorted(
        (item for item in sources if item.experience_id in active_ids),
        key=lambda item: (item.experience_id, item.reflection_id),
    )
    return ExperienceSnapshot(
        version=version,
        experiences=active,
        sources=linked_sources,
        content_hash=_canonical_hash(active, linked_sources),
    )


def add_source_task_types(
    snapshot: ExperienceSnapshot,
    version: str,
    task_categories: dict[str, str],
) -> ExperienceSnapshot:
    """Add trusted source-task categories without removing model-generated tags."""
    missing = sorted(
        {source.task_id for source in snapshot.sources} - set(task_categories)
    )
    if missing:
        raise ValueError(f"Missing source task categories: {missing}")
    categories_by_experience: dict[str, set[str]] = {}
    for source in snapshot.sources:
        categories_by_experience.setdefault(source.experience_id, set()).add(
            task_categories[source.task_id]
        )
    experiences = [
        item.model_copy(
            update={
                "task_types": sorted(
                    set(item.task_types) | categories_by_experience[item.experience_id]
                )
            }
        )
        for item in snapshot.experiences
    ]
    return create_snapshot(version, experiences, snapshot.sources)


def add_execution_contracts(
    snapshot: ExperienceSnapshot,
    version: str,
    contracts: dict[str, ExperienceExecutionContract],
) -> ExperienceSnapshot:
    """Attach Train-authored execution contracts to every active Experience."""
    experience_ids = {item.experience_id for item in snapshot.experiences}
    missing = sorted(experience_ids - set(contracts))
    unknown = sorted(set(contracts) - experience_ids)
    if missing or unknown:
        raise ValueError(
            f"Execution contract IDs differ from snapshot: missing={missing}, unknown={unknown}"
        )
    experiences = [
        item.model_copy(update={"execution_contract": contracts[item.experience_id]})
        for item in snapshot.experiences
    ]
    return create_snapshot(version, experiences, snapshot.sources)


def write_snapshot(snapshot: ExperienceSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")


def load_snapshot(path: Path) -> ExperienceSnapshot:
    snapshot = ExperienceSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    expected = _canonical_hash(snapshot.experiences, snapshot.sources)
    if snapshot.content_hash != expected:
        raise ValueError("Experience snapshot hash does not match its contents")
    return snapshot
