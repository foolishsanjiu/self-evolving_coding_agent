"""Versioned trajectory recording and lightweight behavior analysis."""

from evodev.trajectory.analyzer import TraceAnalyzer
from evodev.trajectory.models import (
    TRAJECTORY_FORMAT_VERSION,
    ArtifactReference,
    RunMetadata,
    TrajectoryEvent,
    tool_catalog_hash,
)
from evodev.trajectory.recorder import TrajectoryRecorder
from evodev.trajectory.redaction import REDACTED, SecretRedactor

__all__ = [
    "REDACTED",
    "TRAJECTORY_FORMAT_VERSION",
    "ArtifactReference",
    "RunMetadata",
    "SecretRedactor",
    "TraceAnalyzer",
    "TrajectoryEvent",
    "TrajectoryRecorder",
    "tool_catalog_hash",
]
