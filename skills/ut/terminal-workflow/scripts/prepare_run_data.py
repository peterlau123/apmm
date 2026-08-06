#!/usr/bin/env python3
"""prepare_run_data.py - Step 3/5: prepare manifest, test_load, workflow_state

After the user confirms parameters (Step 2), this script creates all data
files needed for the workflow loop:
  1. Copies manifest_source -> run_dir/manifest.json, OR
     copies test_list.txt -> run_dir/ and generates manifest.json from it
  2. Creates workflow_state.json (schema-validated)
  3. Calls generate_test_load.py to create test_load_xxx.json
  4. Updates workflow_state.json with the test_load path

Replaces the old multi-step init (manifest copy/gen + init_workflow_state +
generate_test_load) with a single deterministic script.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.ut.ut_common import load_workflow_yaml
from skills.ut.ut_common import validate_and_write

SHARED_DIR = Path(__file__).resolve().parent.parent.parent  # skills/ut/ut_common/


def _copy_manifest(manifest_source: Path, run_dir: Path):
    """Copy an existing manifest.json into run_dir.

    Returns (manifest_path, test_list_in_run_dir, test_count).
    """
    manifest_path = run_dir / "manifest.json"
    shutil.copy2(manifest_source, manifest_path)

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    test_count = len(data.get("tests", []))
    return manifest_path, None, test_count


def _build_manifest_from_test_list(test_list_path: Path, run_dir: Path):
    """Copy test_list.txt into run_dir and generate manifest.json from it.

    Returns (manifest_path, test_list_in_run_dir, test_count).
    """
    dest_test_list = run_dir / "test_list.txt"
    shutil.copy2(test_list_path, dest_test_list)

    with open(dest_test_list, encoding="utf-8") as f:
        lines = [
            line.strip()
            for line in f.read().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    tests = []
    for i, node in enumerate(lines):
        parts = node.split("::")
        test_file = parts[0] if len(parts) >= 1 else node
        test_name = parts[1] if len(parts) >= 2 else ""
        tests.append({
            "id": i + 1,
            "test_node": node,
            "test_file": test_file,
            "test_name": test_name,
            "status": "pending",
        })

    manifest = {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "test_list_file",
        "tests": tests,
        "statistics": {"total": len(tests), "pending": len(tests)},
    }

    manifest_path = run_dir / "manifest.json"
    is_valid, errors = validate_and_write(manifest, "manifest", manifest_path)
    if not is_valid:
        print(f"[ERROR] manifest schema validation failed: {errors}", file=sys.stderr)
        sys.exit(1)
    return manifest_path, dest_test_list, len(tests)


def _create_workflow_state(
    run_dir: Path,
    workflow_yaml_path: Path,
    manifest_path: Path,
    test_list_path,
    test_count: int,
    config: dict,
) -> Path:
    """Create and validate workflow_state.json.

    Returns the path to the created workflow_state.json.
    """
    workflow_cfg = config.get("workflow", {})
    now = datetime.now(timezone.utc).isoformat()
    state_path = run_dir / "workflow_state.json"

    state = {
        "workflow": {
            "name": workflow_cfg.get("name", "UT Test Workflow"),
            "version": workflow_cfg.get("version", "2.0"),
            "test_name": workflow_cfg.get("test_name", "ut"),
            "started_at": now,
            "status": "running",
        },
        "current_stage": "collect",
        "iteration": 0,
        "paths": {
            "run_dir": str(run_dir),
            "workflow_yaml": str(workflow_yaml_path),
            "manifest": str(manifest_path),
            "test_list": str(test_list_path) if test_list_path else None,
            "manifest_schema": str(SHARED_DIR / "manifest_schema.json"),
            "batches_dir": str(run_dir / "batches"),
            "logs_dir": str(run_dir / "logs"),
            "reports_dir": str(run_dir / "reports"),
            "workflow_state": str(state_path),
        },
        "stats": {
            "total_tests": test_count,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "ignored": 0,
            "pending": test_count,
            "error_rate": 0.0,
        },
        "current_batch": {"batch_id": None, "size": 0, "started_at": None},
        "flags": {
            "stop_requested": False,
            "pause_requested": False,
            "pause_reason": None,
            "consecutive_failures": 0,
        },
        "last_update": now,
        "last_worker_result": {
            "stats": {"passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 0},
            "next_action": "continue",
            "error": None,
            "blocked_reason": None,
        },
    }

    is_valid, errors = validate_and_write(state, "workflow_state", state_path)
    if not is_valid:
        print(f"[ERROR] workflow_state schema validation failed: {errors}", file=sys.stderr)
        sys.exit(1)
    return state_path


def _generate_test_load(
    manifest_path: Path,
    run_dir: Path,
    state_path: Path,
    test_load_count: int,
) -> None:
    """Call generate_test_load.py to create test_load_xxx.json.

    Hard-fails (sys.exit) if the script is missing or returns non-zero.
    """
    gtl_script = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "generate_test_load.py"
    if not gtl_script.exists():
        print(f"[ERROR] generate_test_load.py not found: {gtl_script}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [
            sys.executable, str(gtl_script),
            "--manifest-path", str(manifest_path),
            "--count", str(test_load_count),
            "--output-dir", str(run_dir),
            "--workflow-state", str(state_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        print(
            f"[ERROR] generate_test_load.py failed (rc={result.returncode})",
            file=sys.stderr,
        )
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}", file=sys.stderr)
        sys.exit(1)

    print(f"[prepare] test_load generated (count={test_load_count})")


def main():
    parser = argparse.ArgumentParser(
        description="Step 3/5: prepare manifest, test_load, workflow_state"
    )
    parser.add_argument(
        "--run-dir", "-d", required=True,
        help="Path to run directory (created by create_run_dir.py)",
    )
    parser.add_argument(
        "--test-list", "-t", default=None,
        help="Override test_list.txt path",
    )
    parser.add_argument(
        "--manifest-source", "-m", default=None,
        help="Override manifest.json source path",
    )
    parser.add_argument(
        "--test-load-count", "-c", type=int, default=None,
        help="Override test_load count (default: from yaml)",
    )
    parser.add_argument(
        "--mode", default="terminal",
        choices=["terminal", "hermes"],
        help="Channel mode (affects log prefix only)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"[ERROR] run_dir not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    workflow_yaml_path = run_dir / "workflow.yaml"
    if not workflow_yaml_path.exists():
        print(
            f"[ERROR] workflow.yaml not found in run_dir: {workflow_yaml_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    config = load_workflow_yaml(workflow_yaml_path)
    input_filter = config.get("input_filter", {})
    app_config = config.get("config", {})
    workflow_cfg = config.get("workflow", {})

    # Resolve test_list path (CLI override > yaml config)
    test_list_path = Path(args.test_list) if args.test_list else None
    if not test_list_path and input_filter.get("test_list_path"):
        test_list_path = Path(input_filter["test_list_path"])

    # Resolve manifest source (CLI override > yaml config)
    manifest_source = Path(args.manifest_source) if args.manifest_source else None
    if not manifest_source and input_filter.get("manifest_source"):
        manifest_source = Path(input_filter["manifest_source"])

    # Resolve test_load count (CLI override > yaml config > default 1000)
    test_load_count = args.test_load_count or workflow_cfg.get(
        "test_load", {}
    ).get("count", 1000)

    # --- Step 1: Create manifest.json ---
    if manifest_source:
        manifest_path, test_list_in_run_dir, test_count = _copy_manifest(
            manifest_source, run_dir
        )
        print(f"[{args.mode}] manifest copied: {test_count} tests")
    elif test_list_path:
        manifest_path, test_list_in_run_dir, test_count = _build_manifest_from_test_list(
            test_list_path, run_dir
        )
        print(f"[{args.mode}] manifest generated: {test_count} tests")
    else:
        print(
            "[ERROR] manifest_source and test_list_path both missing",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Step 2: Create workflow_state.json ---
    state_path = _create_workflow_state(
        run_dir, workflow_yaml_path, manifest_path,
        test_list_in_run_dir, test_count, config,
    )
    print(f"[{args.mode}] workflow_state created")

    # --- Step 3: Generate test_load ---
    _generate_test_load(manifest_path, run_dir, state_path, test_load_count)

    # --- Output summary ---
    print("---")
    print("run_dir:", run_dir)
    print("manifest:", manifest_path)
    print("test_list:", test_list_in_run_dir)
    print("workflow_state:", state_path)
    print("total_tests:", test_count)
    print("test_load_count:", test_load_count)
    print("batch_size:", app_config.get("batch_size", 8))
    print("execution_strategy:", workflow_cfg.get("execution_strategy", "single-phase"))
    print("resume_from:", app_config.get("resume_from"))
    print("...")


if __name__ == "__main__":
    main()
