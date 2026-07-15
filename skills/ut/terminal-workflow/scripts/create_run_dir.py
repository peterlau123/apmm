#!/usr/bin/env python3
"""create_run_dir.py - Step 1/5: create run dir + copy workflow.yaml

Creates the run directory structure and copies the workflow.yaml into it.
Does NOT create manifest.json, workflow_state.json, or test_load - those are
created by prepare_run_data.py in Step 3 after the user confirms parameters.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.ut.shared import create_run_dir as _create_run_dir
from skills.ut.shared import load_workflow_yaml


def main():
    parser = argparse.ArgumentParser(
        description="Step 1/5: create run dir + copy workflow.yaml"
    )
    parser.add_argument(
        "--workflow-yaml", "-y", required=True,
        help="Path to source workflow.yaml",
    )
    parser.add_argument(
        "--mode", default="terminal",
        choices=["terminal", "hermes"],
        help="Channel mode (affects log prefix only)",
    )
    args = parser.parse_args()

    source_yaml = Path(args.workflow_yaml)
    if not source_yaml.exists():
        print(f"[ERROR] workflow.yaml not found: {source_yaml}", file=sys.stderr)
        sys.exit(1)

    config = load_workflow_yaml(source_yaml)
    test_name = config.get("workflow", {}).get("test_name", "ut")
    run_dir = _create_run_dir(test_name=test_name, workflow_yaml_path=source_yaml)

    # Copy workflow.yaml into run_dir (original is NEVER modified)
    target_yaml = run_dir / "workflow.yaml"
    shutil.copy2(source_yaml, target_yaml)

    # Create standard subdirectories
    for subdir in ("batches", "logs", "reports"):
        (run_dir / subdir).mkdir(exist_ok=True)

    # Update current_run.json pointer
    agents_dir = PROJECT_ROOT / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    pointer_file = agents_dir / "current_run.json"
    pointer_data = {
        "run_dir": str(run_dir),
        "workflow_yaml_path": str(target_yaml),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(pointer_file, "w", encoding="utf-8") as f:
        json.dump(pointer_data, f, indent=2)

    print(f"[{args.mode}] run_dir ready: {run_dir}")

    # Output structured YAML block for the Agent to display to the user
    workflow_cfg = config.get("workflow", {})
    input_filter = config.get("input_filter", {})
    app_config = config.get("config", {})

    print("---")
    print("run_dir:", run_dir)
    print("params:")
    params = [
        ("test_list_path", input_filter.get("test_list_path")),
        ("manifest_source", input_filter.get("manifest_source")),
        ("execution_strategy", workflow_cfg.get("execution_strategy", "single-phase")),
        ("test_load_count", workflow_cfg.get("test_load", {}).get("count", 1000)),
        ("batch_size", app_config.get("batch_size", 8)),
        ("max_retry", app_config.get("max_retry_per_test", 3)),
        ("resume_from", app_config.get("resume_from")),
    ]
    for key, value in params:
        print(f"  {key}: {value}")
    print("...")


if __name__ == "__main__":
    main()
