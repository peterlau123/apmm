#!/usr/bin/env python3
"""
merge_batch_manifests.py - Merge batch execution results back into input manifest.json

Purpose:
  When running hermes workflow with kanban=off in production mode:
  - Input manifest: tasks/ut/dataset/manifest.json (DO NOT modify directly)
  - Each batch produces: batch_results.json + handled_tests.json
  - This script merges all batch results back into the input manifest

Workflow:
  1. Load input manifest.json (preserve original, create a working copy)
  2. Discover all batch directories with results
  3. For each batch, apply batch_results.json + handled_tests.json updates
  4. Write merged manifest to output path (default: same as input with "_merged" suffix)

Usage:
    python tasks/ut/scripts/merge_batch_manifests.py \
        --input tasks/ut/dataset/manifest.json \
        --run-dir runs/ut-20260627-123456 \
        --output runs/ut-20260627-123456/manifest_final.json

    # Or merge all batches from a run directory:
    python tasks/ut/scripts/merge_batch_manifests.py \
        --run-dir runs/ut-20260627-123456 \
        --output tasks/ut/dataset/manifest_merged.json

Design: tasks/ut/docs/designs/2026-06-27-batch-manifest-merge-design.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_manifest(path: Path) -> dict:
    """Load manifest.json from path."""
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict, path: Path, backup: bool = True) -> None:
    """Save manifest.json to path with optional backup."""
    if backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.parent / f"{path.stem}_backup_{timestamp}.json"
        import shutil
        shutil.copy2(path, backup_path)
        print(f"[INFO] Backup created: {backup_path}")

    manifest["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Manifest saved: {path}")


def calculate_statistics(tests: list[dict]) -> dict:
    """Calculate statistics from test statuses."""
    stats = defaultdict(int)
    for test in tests:
        status = test.get("status", "pending")
        stats[status] += 1

    total = len(tests)
    executed = total - stats.get("pending", 0)
    progress = (executed / total * 100) if total > 0 else 0.0
    pass_rate = (stats.get("passed", 0) / executed * 100) if executed > 0 else 0.0

    return {
        "total": total,
        "executed": executed,
        "progress": round(progress, 2),
        "pass_rate": round(pass_rate, 2),
        "passed": stats.get("passed", 0),
        "failed": stats.get("failed", 0),
        "error": stats.get("error", 0) + stats.get("retriable_error", 0),
        "ignored": stats.get("ignored", 0),
        "pending": stats.get("pending", 0),
        "retriable_error": stats.get("retriable_error", 0),
        "fixed_pending_verify": stats.get("fixed_pending_verify", 0),
    }


def merge_batch_results(manifest: dict, batch_results: dict, handled: dict | None = None, strategy: str = "all") -> dict:
    """Merge batch_results and handled_tests into manifest.

    This follows the v5 merge logic from update_manifest.py:
    - For each test in batch_results["tests"]:
        - Set last_batch_id = batch_results["batch_id"]
        - Copy error_type, error_message, duration_ms, exit_code, log_path
        - Increment retry_count for failed/retriable_error/error
        - Update status (with max_retry check for retriable_error)

    - For each test in handled_tests["tests"]:
        - Apply status override
        - Apply ignore_reason if present
        - Apply resolution details (errors[], failures[])

    Args:
        manifest: Input manifest dict
        batch_results: Batch execution results
        handled: Optional handled_tests overrides
        strategy: "all" (default) or "passed-only"
            - all: Update all test statuses (passed, failed, error)
            - passed-only: Only update tests with status="passed"
    """
    tests = manifest.get("tests", [])
    by_id = {t.get("id"): t for t in tests if t.get("id") is not None}
    by_node = {t.get("test_node"): t for t in tests if t.get("test_node")}

    def _find(result: dict) -> dict | None:
        """Find test in manifest by id or test_node."""
        tid = result.get("id")
        if tid is not None and tid in by_id:
            return by_id[tid]
        node = result.get("test_node")
        if node and node in by_node:
            return by_node[node]
        return None

    batch_id = batch_results.get("batch_id")

    # Apply batch_results updates
    for result in batch_results.get("tests", []):
        target = _find(result)
        if target is None:
            continue

        new_status = result.get("status", target.get("status", "pending"))

        # Strategy filter: passed-only skips non-passed tests
        if strategy == "passed-only" and new_status != "passed":
            continue

        # Set last_batch_id
        if batch_id is not None:
            target["last_batch_id"] = batch_id

        # Copy execution details
        if result.get("error_type"):
            target["error_type"] = result["error_type"]
        if result.get("error_message"):
            target["error_message"] = result["error_message"]
        if result.get("duration_ms"):
            target["last_duration_ms"] = result["duration_ms"]
        if result.get("exit_code"):
            target["last_exit_code"] = result["exit_code"]
        if result.get("log_path"):
            target["log_file"] = result["log_path"]

        # Increment counters
        target["run_count"] = int(target.get("run_count", 0)) + 1

        prev_status = target.get("status", "pending")
        has_failed_before = prev_status in ("failed", "retriable_error", "error")

        # Increment retry_count if this is a retry (previous was failed)
        if has_failed_before and new_status in ("failed", "retriable_error", "error"):
            target["retry_count"] = int(target.get("retry_count", 0)) + 1

        # Apply status with max_retry check
        max_retry = int(target.get("max_retry", 3))
        if new_status == "retriable_error" and target.get("retry_count", 0) >= max_retry:
            target["status"] = "ignored"
            et = target.get("error_type", result.get("error_type") or "unknown")
            target["ignored_reason"] = f"max retry exceeded for {et}"
        else:
            target["status"] = new_status

        target["last_run_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Apply handled_tests overrides
    if handled:
        for handled_test in handled.get("tests", []):
            target = _find(handled_test)
            if target is None:
                continue

            # Status override
            if "status" in handled_test or "final_status" in handled_test:
                target["status"] = handled_test.get("final_status") or handled_test.get("status")

            # Ignore reason
            if "ignore_reason" in handled_test or "ignored_reason" in handled_test:
                target["ignored_reason"] = handled_test.get("ignore_reason") or handled_test.get("ignored_reason")

            # Resolution details
            if handled_test.get("errors"):
                target["errors"] = handled_test["errors"]
            if handled_test.get("failures"):
                target["failures"] = handled_test["failures"]

            # Commit if fix applied
            if handled_test.get("commit"):
                target["fix_applied"] = True
                target["fix_details"] = {
                    "commit": handled_test["commit"],
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

    # Recalculate statistics
    manifest["statistics"] = calculate_statistics(tests)
    return manifest


def discover_run_files(run_dir: Path) -> tuple[Path, list[Path]]:
    """Auto-discover manifest and batches in run directory.

    Returns:
        (manifest_path, batch_dirs)

    Raises:
        FileNotFoundError: No manifest.json or batches/
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")

    batches_dir = run_dir / "batches"
    if not batches_dir.exists():
        raise FileNotFoundError(f"batches/ not found: {batches_dir}")

    batch_dirs = []
    for batch_dir in sorted(batches_dir.iterdir()):
        if batch_dir.is_dir() and (batch_dir / "batch_results.json").exists():
            batch_dirs.append(batch_dir)

    if not batch_dirs:
        raise FileNotFoundError(f"No batch_results.json found in: {batches_dir}")

    return manifest_path, batch_dirs


def discover_batches(run_dir: Path) -> list[Path]:
    """Discover all batch directories with batch_results.json."""
    batches_dir = run_dir / "batches"
    if not batches_dir.exists():
        return []

    batch_dirs = []
    for batch_dir in sorted(batches_dir.iterdir()):
        if batch_dir.is_dir() and (batch_dir / "batch_results.json").exists():
            batch_dirs.append(batch_dir)

    return batch_dirs


def merge_all_batches(
    input_manifest_path: Path,
    run_dir: Path,
    output_path: Path | None = None,
) -> dict:
    """Merge all batch results from run_dir into input manifest.

    Process:
    1. Load input manifest
    2. Discover all batch directories
    3. For each batch (in order):
        - Load batch_results.json
        - Load handled_tests.json if exists
        - Apply merge
    4. Save merged manifest to output_path
    """
    # Load input manifest
    manifest = load_manifest(input_manifest_path)
    print(f"[INFO] Input manifest: {input_manifest_path}")
    print(f"[INFO] Tests: {len(manifest.get('tests', []))}")

    # Discover batches
    batch_dirs = discover_batches(run_dir)
    if not batch_dirs:
        print(f"[WARN] No batch results found in: {run_dir}")
        return manifest

    print(f"[INFO] Found {len(batch_dirs)} batch directories")

    # Merge each batch
    merged_count = 0
    for batch_dir in batch_dirs:
        batch_results_path = batch_dir / "batch_results.json"
        handled_tests_path = batch_dir / "handled_tests.json"

        batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))
        handled_tests = None
        if handled_tests_path.exists():
            handled_tests = json.loads(handled_tests_path.read_text(encoding="utf-8"))

        batch_id = batch_results.get("batch_id", batch_dir.name)
        test_count = len(batch_results.get("tests", []))

        manifest = merge_batch_results(manifest, batch_results, handled_tests)
        merged_count += test_count
        print(f"[MERGE] {batch_id}: {test_count} tests")

    # Update metadata
    manifest["merged_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["merged_from_run"] = str(run_dir)
    manifest["merged_batches"] = len(batch_dirs)

    # Determine output path
    if output_path is None:
        output_path = run_dir / "manifest_merged.json"

    # Save merged manifest
    save_manifest(manifest, output_path, backup=False)

    stats = manifest.get("statistics", {})
    print(f"\n[SUMMARY]")
    print(f"  Input tests: {len(manifest.get('tests', []))}")
    print(f"  Batches merged: {len(batch_dirs)}")
    print(f"  Tests updated: {merged_count}")
    print(f"  Final stats: passed={stats.get('passed', 0)}, failed={stats.get('failed', 0)}, "
          f"error={stats.get('error', 0)}, ignored={stats.get('ignored', 0)}, pending={stats.get('pending', 0)}")

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge batch execution results into manifest.json"
    )

    parser.add_argument(
        "--run-dir", "-r",
        required=True,
        help="Run directory containing manifest.json and batches/",
    )

    parser.add_argument(
        "--strategy",
        choices=["all", "passed-only"],
        default="all",
        help="Update strategy: 'all' (default) or 'passed-only' (只更新passed状态)",
    )

    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path (default: 原地更新run_dir/manifest.json)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be merged without writing",
    )

    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    strategy = args.strategy

    # Auto-discover
    try:
        manifest_path, batch_dirs = discover_run_files(run_dir)
        print(f"[INFO] Found manifest: {manifest_path}")
        print(f"[INFO] Found {len(batch_dirs)} batches")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    manifest = load_manifest(manifest_path)

    merged_count = 0
    for batch_dir in batch_dirs:
        batch_results_path = batch_dir / "batch_results.json"
        handled_tests_path = batch_dir / "handled_tests.json"

        batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))
        handled_tests = None
        if handled_tests_path.exists():
            handled_tests = json.loads(handled_tests_path.read_text(encoding="utf-8"))

        batch_id = batch_results.get("batch_id", batch_dir.name)
        test_count = len(batch_results.get("tests", []))

        manifest = merge_batch_results(manifest, batch_results, handled_tests, strategy)
        merged_count += test_count
        print(f"[MERGE] {batch_id}: {test_count} tests (strategy={strategy})")

    # Update metadata
    manifest["merged_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["merged_from_run"] = str(run_dir)
    manifest["merged_batches"] = len(batch_dirs)
    manifest["merge_strategy"] = strategy

    if args.dry_run:
        print("\n[DRY RUN] No output written")
        stats = manifest.get("statistics", {})
        print(f"  passed={stats.get('passed', 0)}, failed={stats.get('failed', 0)}, "
              f"error={stats.get('error', 0)}, ignored={stats.get('ignored', 0)}, pending={stats.get('pending', 0)}")
        return 0

    output_path = Path(args.output) if args.output else manifest_path
    save_manifest(manifest, output_path, backup=True)

    stats = manifest.get("statistics", {})
    print(f"\n[SUMMARY]")
    print(f"  Tests updated: {merged_count}")
    print(f"  Strategy: {strategy}")
    print(f"  Output: {output_path}")
    print(f"  passed={stats.get('passed', 0)}, failed={stats.get('failed', 0)}, "
          f"error={stats.get('error', 0)}, ignored={stats.get('ignored', 0)}, pending={stats.get('pending', 0)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())