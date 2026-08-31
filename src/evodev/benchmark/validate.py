"""One-command qualification for the frozen EvoDev benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evodev.benchmark.loader import BenchmarkLoader
from evodev.benchmark.qa import BenchmarkQA


def validate_benchmark(
    benchmark_root: Path,
    work_root: Path | None = None,
) -> dict[str, Any]:
    loader = BenchmarkLoader(benchmark_root)
    manifest = loader.verify_manifest()
    results = BenchmarkQA(work_root).validate_all(loader.load_tasks())
    return {
        "benchmark_version": manifest.benchmark_version,
        "benchmark_hash": manifest.manifest_hash,
        "task_count": len(results),
        "valid": True,
        "tasks": [
            {
                "task_id": result.task_id,
                "before_exit_code": result.before_exit_code,
                "after_exit_code": result.after_exit_code,
                "original_failed": result.original_failed,
                "gold_passed": result.gold_passed,
                "valid": result.valid,
            }
            for result in results
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate EvoDev Benchmark integrity and discriminative power."
    )
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmarks"))
    parser.add_argument("--work-root", type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    report = validate_benchmark(arguments.benchmark_root, arguments.work_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
