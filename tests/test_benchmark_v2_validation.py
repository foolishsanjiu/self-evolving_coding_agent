from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from evodev.benchmark import BenchmarkQA, BenchmarkTask, BenchmarkTaskConfig

VALIDATION_ROOT = Path("benchmarks-v2/validation")
VALIDATION_QA_PATH = Path("benchmarks-v2/validation-qa.json")


def _load_task(path: Path) -> BenchmarkTask:
    config = BenchmarkTaskConfig.model_validate(
        yaml.safe_load((path / "task.yaml").read_text(encoding="utf-8"))
    )
    return BenchmarkTask(
        split="validation",
        config=config,
        task_path=path.resolve(),
        repository_path=(path / "repo").resolve(),
        public_tests_path=(path / "repo" / "tests").resolve(),
        hidden_target_tests_path=(path / "hidden_tests" / "target").resolve(),
        hidden_regression_tests_path=(path / "hidden_tests" / "regression").resolve(),
        gold_patch_path=(path / "gold.patch").resolve(),
    )


TASKS = [_load_task(path) for path in sorted(VALIDATION_ROOT.glob("task_*"))]
TASKS_BY_ID = {task.config.task_id: task for task in TASKS}

GOLD_REGRESSIONS = [
    pytest.param(
        "task_109",
        [
            (
                "tokens/service.py",
                "return token.expires_at.astimezone(UTC) <= now.astimezone(UTC)",
                "return token.expires_at.astimezone(UTC) < now.astimezone(UTC)",
            )
        ],
        id="task_109-exclusive-expiry-boundary",
    ),
    pytest.param(
        "task_109",
        [
            (
                "tokens/parser.py",
                "expires_at=expires_at.astimezone(UTC)",
                "expires_at=expires_at",
            )
        ],
        id="task_109-offset-not-normalized",
    ),
    pytest.param(
        "task_110",
        [
            (
                "checkpoints/service.py",
                "while checkpoint + 1 in pending:",
                "if checkpoint + 1 in pending:",
            )
        ],
        id="task_110-only-one-contiguous-step",
    ),
    pytest.param(
        "task_110",
        [
            (
                "checkpoints/service.py",
                "    store.save(updated)",
                "    store.state = updated\n    store.save(updated)",
            )
        ],
        id="task_110-state-mutated-before-persistence",
    ),
    pytest.param(
        "task_111",
        [("http_cache/client.py", "status_code=200,", "status_code=304,")],
        id="task_111-cached-body-keeps-304-status",
    ),
    pytest.param(
        "task_111",
        [
            (
                "http_cache/client.py",
                "if response.status_code == 200 and etag:",
                "if response.status_code >= 200 and etag:",
            )
        ],
        id="task_111-error-response-cached",
    ),
    pytest.param(
        "task_112",
        [
            (
                "resources/manager.py",
                "            cleanup_errors.append(exc)",
                "            cleanup_errors.append(exc)\n            break",
            )
        ],
        id="task_112-cleanup-stops-after-first-error",
    ),
    pytest.param(
        "task_112",
        [
            (
                "resources/manager.py",
                (
                    '            raise primary from ExceptionGroup('
                    '"resource cleanup failed", cleanup_errors)'
                ),
                "            raise cleanup_errors[0] from primary",
            )
        ],
        id="task_112-cleanup-replaces-primary",
    ),
    pytest.param(
        "task_113",
        [
            (
                "profiles/serializer.py",
                "    display_name = payload.get(field)",
                "    display_name = payload.get(field) or None",
            )
        ],
        id="task_113-empty-display-name-coerced",
    ),
    pytest.param(
        "task_113",
        [
            (
                "profiles/serializer.py",
                "    payload[field] = profile.display_name",
                (
                    '    payload["displayName"] = profile.display_name\n'
                    '    payload["display_name"] = profile.display_name'
                ),
            )
        ],
        id="task_113-both-aliases-emitted",
    ),
]


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _pytest_environment() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


def _run_pytest(workspace: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            *paths,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_pytest_environment(),
        timeout=30,
        check=False,
    )


def test_formal_v2_validation_inventory_is_new_and_balanced() -> None:
    qa = json.loads(VALIDATION_QA_PATH.read_text(encoding="utf-8"))
    assert [task.config.task_id for task in TASKS] == [
        f"task_{number}" for number in range(109, 114)
    ]
    assert Counter(task.config.category for task in TASKS) == {
        "cross_module_bug": 1,
        "state_data_flow": 1,
        "feature": 1,
        "error_resilience": 1,
        "test_repair_compatibility": 1,
    }
    assert len({task.config.repository_template for task in TASKS}) == 5
    assert all(task.config.benchmark_version == "2.0" for task in TASKS)
    assert all(task.config.difficulty in {"medium", "hard"} for task in TASKS)
    assert qa["stage"] == "validation_qualified"
    assert qa["formal_manifest_created"] is False
    assert qa["agent_runs"] == 0
    assert qa["paid_debugging"] is False
    assert qa["qa"] == {
        "independent_rounds": 5,
        "public_original_passed": 5,
        "hidden_original_failed": 5,
        "hidden_gold_passed": 5,
        "incomplete_fixes_rejected": 10,
    }
    assert {entry["task_id"]: entry["checksum"] for entry in qa["tasks"]} == {
        task.config.task_id: _tree_digest(task.task_path) for task in TASKS
    }


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_formal_v2_validation_public_tests_pass_original(task: BenchmarkTask) -> None:
    completed = _run_pytest(task.repository_path, "tests")

    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.config.task_id)
def test_formal_v2_validation_original_fails_and_gold_passes(task: BenchmarkTask) -> None:
    result = BenchmarkQA().validate_task(task)

    assert result.original_failed is True
    assert result.gold_passed is True, result.after_output
    assert result.valid is True


@pytest.mark.parametrize(("task_id", "replacements"), GOLD_REGRESSIONS)
def test_validation_hidden_tests_reject_incomplete_gold_regressions(
    tmp_path: Path,
    task_id: str,
    replacements: list[tuple[str, str, str]],
) -> None:
    task = TASKS_BY_ID[task_id]
    workspace = tmp_path / task_id
    shutil.copytree(task.repository_path, workspace)
    subprocess.run(
        ["git", "init", "-q"], cwd=workspace, capture_output=True, check=True
    )
    applied = subprocess.run(
        ["git", "apply", str(task.gold_patch_path)],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    for relative_path, old, new in replacements:
        path = workspace / relative_path
        content = path.read_text(encoding="utf-8")
        assert old in content
        path.write_text(content.replace(old, new, 1), encoding="utf-8")
    hidden = workspace / "hidden_eval"
    shutil.copytree(task.hidden_target_tests_path, hidden / "target")
    shutil.copytree(task.hidden_regression_tests_path, hidden / "regression")

    completed = _run_pytest(workspace, "hidden_eval/target", "hidden_eval/regression")

    assert completed.returncode != 0
