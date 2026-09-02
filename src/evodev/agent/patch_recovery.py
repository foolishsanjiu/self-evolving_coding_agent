"""Normalize file identities used by post-patch-failure recovery guards."""

from typing import Any


def normalize_tool_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def extract_patch_paths(patch: Any) -> set[str]:
    if not isinstance(patch, str):
        return set()

    paths = set()
    for line in patch.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw_path = line[4:].split("\t", 1)[0].strip()
        if raw_path == "/dev/null":
            continue
        if raw_path.startswith(("a/", "b/")):
            raw_path = raw_path[2:]
        if raw_path:
            paths.add(normalize_tool_path(raw_path))
    return paths
