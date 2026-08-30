from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from evodev.sandbox import WorkspaceManager, WorkspaceRun

FIXTURE = Path("fixtures/simple_bug")


def _remove_readonly(
    function: Callable[[str], object],
    path: str,
    _error_info: object,
) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


@pytest.fixture
def runs_root() -> Iterator[Path]:
    path = Path(".test_runtime") / f"workspace_manager_{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, onerror=_remove_readonly)


def test_create_reset_and_cleanup_preserve_original(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    original_content = (FIXTURE / "src/calculator.py").read_text(encoding="utf-8")
    run = manager.create(FIXTURE, run_id="run_test")
    workspace_file = run.workspace_path / "src/calculator.py"

    workspace_file.write_text("changed\n", encoding="utf-8")
    (run.workspace_path / "temporary.txt").write_text("temporary", encoding="utf-8")
    manager.reset(run)

    assert workspace_file.read_text(encoding="utf-8").replace("\r\n", "\n") == original_content
    assert not (run.workspace_path / "temporary.txt").exists()
    assert (FIXTURE / "src/calculator.py").read_text(encoding="utf-8") == original_content

    manager.cleanup(run)

    assert not run.workspace_path.exists()
    assert run.artifacts_path.is_dir()
    assert (run.run_path / "final.patch").is_file()
    assert (run.run_path / "final.diff").is_file()


def test_each_create_uses_an_independent_workspace(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)

    first = manager.create(FIXTURE)
    second = manager.create(FIXTURE)

    assert first.run_id != second.run_id
    assert first.workspace_path != second.workspace_path
    assert first.workspace_path.is_dir() and second.workspace_path.is_dir()


def test_discard_removes_evaluator_workspace_without_final_diff(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    run = manager.create(FIXTURE, run_id="discard_test")

    manager.discard(run)

    assert not run.workspace_path.exists()
    assert not (run.run_path / "final.patch").exists()
    assert not (run.run_path / "final.diff").exists()


def test_rejects_unsafe_run_identifiers_and_foreign_paths(runs_root: Path) -> None:
    manager = WorkspaceManager(runs_root)
    with pytest.raises(ValueError, match="run_id"):
        manager.create(FIXTURE, run_id="../escape")

    foreign = WorkspaceRun(
        run_id="foreign",
        original_path=FIXTURE.resolve(),
        run_path=runs_root.parent / "foreign",
        workspace_path=runs_root.parent / "foreign/workspace",
        artifacts_path=runs_root.parent / "foreign/artifacts",
    )
    with pytest.raises(ValueError, match="outside"):
        manager.cleanup(foreign)


def test_runs_directory_inside_source_is_not_recursively_copied(runs_root: Path) -> None:
    source = runs_root / "source"
    source.mkdir()
    (source / "value.txt").write_text("value", encoding="utf-8")
    (source / ".env").write_text("SECRET=not-copied", encoding="utf-8")
    (source / ".env.example").write_text("SECRET=example", encoding="utf-8")
    manager = WorkspaceManager(source / "runs")

    run = manager.create(source, run_id="nested")

    assert (run.workspace_path / "value.txt").is_file()
    assert not (run.workspace_path / "runs").exists()
    assert not (run.workspace_path / ".env").exists()
    assert (run.workspace_path / ".env.example").is_file()
