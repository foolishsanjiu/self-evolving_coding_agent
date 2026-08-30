"""Small SQLite experience store with merge and provenance."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from evodev.experience.eligibility import can_write_experience
from evodev.experience.models import (
    ExperienceCandidate,
    ExperienceSource,
    ExperienceStatus,
    Reflection,
    StoredExperience,
)
from evodev.trajectory.models import utc_now


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", value.lower()))


class ExperienceStore:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path.resolve()
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"Experience Store does not exist: {self.path}")
            self.connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            self.connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS reflections (
                reflection_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(task_id, run_id)
            );
            CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY, task_types TEXT NOT NULL, trigger TEXT NOT NULL,
                recommendation TEXT NOT NULL, rationale TEXT NOT NULL, keywords TEXT NOT NULL,
                confidence REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experience_sources (
                experience_id TEXT NOT NULL, reflection_id TEXT NOT NULL, run_id TEXT NOT NULL,
                trajectory_path TEXT NOT NULL, evaluation_report_path TEXT NOT NULL,
                PRIMARY KEY (experience_id, reflection_id),
                FOREIGN KEY (experience_id) REFERENCES experiences(experience_id),
                FOREIGN KEY (reflection_id) REFERENCES reflections(reflection_id)
            );
            """
            )

    def close(self) -> None:
        self.connection.close()

    def has_run(self, task_id: str, run_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM reflections WHERE task_id = ? AND run_id = ?",
            (task_id, run_id),
        ).fetchone()
        return row is not None

    def _similar_id(self, candidate: ExperienceCandidate) -> str | None:
        candidate_types = set(candidate.task_types)
        candidate_tokens = _tokens(candidate.trigger) | set(candidate.keywords)
        query = "SELECT * FROM experiences WHERE status != 'deprecated'"
        for row in self.connection.execute(query):
            if not candidate_types.intersection(json.loads(row["task_types"])):
                continue
            stored_tokens = _tokens(row["trigger"]) | set(json.loads(row["keywords"]))
            union = candidate_tokens | stored_tokens
            similarity = len(candidate_tokens & stored_tokens) / len(union) if union else 0
            if similarity >= 0.5:
                return str(row["experience_id"])
        return None

    def add_or_merge(
        self,
        candidate: ExperienceCandidate,
        reflection: Reflection,
        *,
        split: str,
        trajectory_path: Path,
        evaluation_report_path: Path,
    ) -> str:
        if not can_write_experience(split):
            raise PermissionError(f"Experience Store is read-only for split: {split}")
        if self.read_only:
            raise PermissionError("Experience Store was opened read-only")
        now = utc_now()
        with self.connection:
            self.connection.execute(
                "INSERT INTO reflections VALUES (?, ?, ?, ?, ?)",
                (
                    reflection.reflection_id,
                    reflection.task_id,
                    reflection.run_id,
                    reflection.model_dump_json(),
                    reflection.created_at,
                ),
            )
            experience_id = self._similar_id(candidate)
            if experience_id is None:
                experience_id = f"exp_{uuid4().hex}"
                self.connection.execute(
                    "INSERT INTO experiences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        experience_id,
                        json.dumps(candidate.task_types),
                        candidate.trigger,
                        candidate.recommendation,
                        candidate.rationale,
                        json.dumps(sorted(set(candidate.keywords))),
                        candidate.confidence,
                        ExperienceStatus.CANDIDATE.value,
                        now,
                        now,
                    ),
                )
            else:
                self.connection.execute(
                    "UPDATE experiences SET confidence = MAX(confidence, ?), updated_at = ? "
                    "WHERE experience_id = ?",
                    (candidate.confidence, now, experience_id),
                )
            self.connection.execute(
                "INSERT INTO experience_sources VALUES (?, ?, ?, ?, ?)",
                (
                    experience_id,
                    reflection.reflection_id,
                    reflection.run_id,
                    str(trajectory_path),
                    str(evaluation_report_path),
                ),
            )
        return experience_id

    def list_experiences(self) -> list[StoredExperience]:
        return [
            StoredExperience(
                experience_id=row["experience_id"],
                task_types=json.loads(row["task_types"]),
                trigger=row["trigger"],
                recommendation=row["recommendation"],
                rationale=row["rationale"],
                keywords=json.loads(row["keywords"]),
                confidence=row["confidence"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in self.connection.execute("SELECT * FROM experiences ORDER BY created_at")
        ]

    def source_count(self, experience_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM experience_sources WHERE experience_id = ?",
            (experience_id,),
        ).fetchone()
        return int(row["count"])

    def list_sources(self) -> list[ExperienceSource]:
        query = (
            "SELECT s.experience_id, s.reflection_id, r.task_id, s.run_id, "
            "s.trajectory_path, s.evaluation_report_path "
            "FROM experience_sources AS s "
            "JOIN reflections AS r ON r.reflection_id = s.reflection_id "
            "ORDER BY s.experience_id, s.reflection_id"
        )
        return [ExperienceSource(**dict(row)) for row in self.connection.execute(query)]

    def set_status(self, experience_id: str, status: ExperienceStatus) -> None:
        if self.read_only:
            raise PermissionError("Experience Store was opened read-only")
        with self.connection:
            self.connection.execute(
                "UPDATE experiences SET status = ?, updated_at = ? WHERE experience_id = ?",
                (status.value, utc_now(), experience_id),
            )
