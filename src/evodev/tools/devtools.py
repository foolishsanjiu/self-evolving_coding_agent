"""Workspace-bound implementations shared by Native and future MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class PathOutsideWorkspaceError(ValueError):
    """Raised when a requested path escapes the configured workspace."""


class DevToolsService:
    """Read-only development tools constrained to one workspace root."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path.resolve(strict=True)
        if not self.workspace_path.is_dir():
            raise NotADirectoryError(f"Workspace is not a directory: {workspace_path}")

    def _resolve_path(self, requested_path: str) -> Path:
        path = Path(requested_path)
        candidate = path if path.is_absolute() else self.workspace_path / path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace_path)
        except ValueError as exc:
            raise PathOutsideWorkspaceError(
                f"Path is outside workspace: {requested_path}"
            ) from exc
        return resolved

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.workspace_path).as_posix()

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.workspace_path)
        except ValueError:
            return False
        return True

    def list_files(self, path: str = ".", recursive: bool = False) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path}")

        entries = target.rglob("*") if recursive else target.iterdir()
        files = sorted(
            self._relative_path(entry)
            for entry in entries
            if self._is_within_workspace(entry) and entry.is_file()
        )
        return {"path": self._relative_path(target) or ".", "recursive": recursive, "files": files}

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        lines = target.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        actual_end = start_line + len(selected) - 1 if selected else start_line - 1
        return {
            "path": self._relative_path(target),
            "start_line": start_line,
            "end_line": actual_end,
            "content": "\n".join(selected),
        }

    def search_code(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        candidates = [target] if target.is_file() else sorted(target.rglob("*"))
        matches: list[dict[str, Any]] = []

        for candidate in candidates:
            if not self._is_within_workspace(candidate) or not candidate.is_file():
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for index, line in enumerate(lines):
                if query not in line:
                    continue
                context_start = max(0, index - 2)
                context_end = min(len(lines), index + 3)
                matches.append(
                    {
                        "file": self._relative_path(candidate),
                        "line_number": index + 1,
                        "matching_line": line,
                        "small_context": "\n".join(lines[context_start:context_end]),
                    }
                )
                if len(matches) >= max_results:
                    return {"query": query, "path": path, "matches": matches, "truncated": True}

        return {"query": query, "path": path, "matches": matches, "truncated": False}
