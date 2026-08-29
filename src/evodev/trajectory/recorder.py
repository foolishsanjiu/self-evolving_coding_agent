"""Crash-safe append-only trajectory recorder and artifact materializer."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from threading import Lock
from typing import Any

from evodev.agent.events import AgentEvent
from evodev.trajectory.analyzer import TraceAnalyzer
from evodev.trajectory.models import ArtifactReference, RunMetadata, TrajectoryEvent, utc_now
from evodev.trajectory.redaction import SecretRedactor

PERSISTED_EVENT_TYPES = frozenset(
    {
        "RUN_STARTED",
        "MODEL_TURN",
        "TOOL_CALL",
        "TOOL_RESULT",
        "FINAL_ANSWER",
        "RUN_FINISHED",
        "RUN_ERROR",
    }
)


class TrajectoryRecorder:
    """Persist public agent behavior without storing private reasoning."""

    def __init__(
        self,
        run_path: Path,
        metadata: RunMetadata,
        *,
        known_secrets: list[str] | None = None,
        env_file: Path | None = None,
        max_inline_chars: int = 4_000,
    ) -> None:
        if max_inline_chars < 1:
            raise ValueError("max_inline_chars must be positive")
        self.run_path = run_path.resolve()
        self.run_path.mkdir(parents=True, exist_ok=True)
        self.artifacts_path = self.run_path / "artifacts"
        self.artifacts_path.mkdir(exist_ok=True)
        self.run_json_path = self.run_path / "run.json"
        self.events_path = self.run_path / "events.jsonl"
        self.trace_features_path = self.run_path / "trace_features.json"
        self.redactor = SecretRedactor(known_secrets, env_file)
        self.max_inline_chars = max_inline_chars
        self._lock = Lock()

        if self.run_json_path.exists():
            stored = RunMetadata.model_validate_json(
                self.run_json_path.read_text(encoding="utf-8")
            )
            if stored.run_id != metadata.run_id or stored.task_id != metadata.task_id:
                raise ValueError("Existing run metadata does not match the requested run")
            self.metadata = stored
        else:
            self.metadata = metadata
            self._write_json_atomic(self.run_json_path, metadata.model_dump(mode="json"))
        self._sequence = self._recover_sequence()

    def _write_json_atomic(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        sanitized = self.redactor.redact(value)
        temporary.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _recover_sequence(self) -> int:
        if not self.events_path.exists():
            self.events_path.touch()
            return 0
        sequence = 0
        valid_bytes = 0
        with self.events_path.open("rb+") as stream:
            while line := stream.readline():
                try:
                    event = TrajectoryEvent.model_validate_json(line)
                except Exception:
                    stream.truncate(valid_bytes)
                    break
                if event.seq != sequence + 1:
                    stream.truncate(valid_bytes)
                    break
                sequence = event.seq
                valid_bytes = stream.tell()
        return sequence

    @staticmethod
    def _safe_name(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
        return normalized[:80] or "artifact"

    def _artifact_reference(
        self,
        path: Path,
        *,
        truncated_for_llm: bool,
    ) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        sanitized = self.redactor.redact_text(text)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")
        digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        reference = ArtifactReference(
            artifact_ref=path.relative_to(self.run_path).as_posix(),
            sha256=digest,
            chars=len(sanitized),
            truncated_for_llm=truncated_for_llm,
        )
        return reference.model_dump(mode="json")

    def _store_artifact(
        self,
        text: str,
        name: str,
        *,
        truncated_for_llm: bool,
    ) -> dict[str, Any]:
        filename = f"{self._sequence + 1:06d}_{self._safe_name(name)}.txt"
        path = self.artifacts_path / filename
        path.write_text(self.redactor.redact_text(text), encoding="utf-8")
        return self._artifact_reference(path, truncated_for_llm=truncated_for_llm)

    def _replace_large_values(
        self,
        value: Any,
        path: str,
        *,
        truncated_for_llm: bool,
    ) -> Any:
        if isinstance(value, str) and len(value) > self.max_inline_chars:
            return self._store_artifact(
                value,
                path,
                truncated_for_llm=truncated_for_llm,
            )
        if isinstance(value, dict):
            if {"artifact_ref", "sha256", "chars", "truncated_for_llm"}.issubset(value):
                return value
            return {
                key: self._replace_large_values(
                    item,
                    f"{path}_{key}",
                    truncated_for_llm=truncated_for_llm,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._replace_large_values(
                    item,
                    f"{path}_{index}",
                    truncated_for_llm=truncated_for_llm,
                )
                for index, item in enumerate(value)
            ]
        return value

    def _prepare_tool_result(self, data: dict[str, Any]) -> dict[str, Any]:
        prepared = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        result = prepared.get("result")
        if not isinstance(result, dict):
            return prepared
        result_data = result.get("data")
        if not isinstance(result_data, dict):
            result_data = {}

        content = result.get("content")
        if isinstance(content, str):
            try:
                if json.loads(content) == result_data:
                    result["content"] = "[structured result stored in data]"
            except (json.JSONDecodeError, TypeError):
                pass

        truncated = bool(result_data.get("output_truncated", False))
        artifact_dir_value = result_data.get("artifact_path")
        if isinstance(artifact_dir_value, str):
            artifact_dir = Path(artifact_dir_value).resolve()
            try:
                artifact_dir.relative_to(self.artifacts_path)
            except ValueError:
                artifact_dir = None
            if artifact_dir is not None and artifact_dir.is_dir():
                for stream_name in ("stdout", "stderr"):
                    stream_path = artifact_dir / f"{stream_name}.txt"
                    if stream_path.is_file():
                        result_data[stream_name] = self._artifact_reference(
                            stream_path,
                            truncated_for_llm=truncated,
                        )
                result_data["artifact_path"] = artifact_dir.relative_to(
                    self.run_path
                ).as_posix()

        call_id = str(result.get("call_id", "tool_result"))
        return self._replace_large_values(
            prepared,
            call_id,
            truncated_for_llm=truncated,
        )

    def _prepare_data(self, event: AgentEvent) -> dict[str, Any]:
        if event.type == "TOOL_RESULT":
            prepared = self._prepare_tool_result(event.data)
        else:
            prepared = json.loads(json.dumps(event.data, ensure_ascii=False, default=str))
            prepared = self._replace_large_values(
                prepared,
                event.type.lower(),
                truncated_for_llm=False,
            )
        return self.redactor.redact(prepared)

    def emit(self, event: AgentEvent) -> None:
        """Append and flush one allowed event; ignore non-schema retry telemetry."""
        if event.type == "TOOL_RETRY":
            return
        if event.type not in PERSISTED_EVENT_TYPES:
            raise ValueError(f"Unsupported trajectory event type: {event.type}")
        with self._lock:
            record = TrajectoryEvent(
                seq=self._sequence + 1,
                type=event.type,
                data=self._prepare_data(event),
            )
            encoded = record.model_dump_json() + "\n"
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._sequence = record.seq
            if event.type == "RUN_FINISHED":
                self._finalize_locked(str(event.data.get("status", "UNKNOWN")))

    def _finalize_locked(self, status: str) -> None:
        self.metadata = self.metadata.model_copy(
            update={"finished_at": utc_now(), "status": status}
        )
        self._write_json_atomic(
            self.run_json_path,
            self.metadata.model_dump(mode="json"),
        )
        features = TraceAnalyzer().analyze_file(self.events_path)
        self._write_json_atomic(self.trace_features_path, features)

    def finalize(self, status: str) -> None:
        """Finalize metadata/features when a caller terminates outside ReActAgent."""
        with self._lock:
            self._finalize_locked(status)

    def write_final_artifacts(self, final_patch: str, final_diff: str) -> None:
        """Persist redacted final code artifacts at stable run-level paths."""
        (self.run_path / "final.patch").write_text(
            self.redactor.redact_text(final_patch), encoding="utf-8"
        )
        (self.run_path / "final.diff").write_text(
            self.redactor.redact_text(final_diff), encoding="utf-8"
        )
