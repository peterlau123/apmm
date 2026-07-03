#!/usr/bin/env python3
"""loop_executor.py - terminal-workflow 自检补救执行器"""

import json
from pathlib import Path
from datetime import datetime
import sys
import os

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.shared.workflow_state_manager import (
    load_workflow_state, update_batch_generated,
    update_batch_running, update_batch_completed
)
from skills.ut.batch_selector.scripts.generate_batch import generate_batch_from_workflow_state
from skills.ut.unit_test_executor.scripts.execute_batch import execute_batch


def check_batch_state(workflow_state_path, batch_id, expected_status):
    state = load_workflow_state(workflow_state_path)
    return batch_id in state.get("batches", {}) and \
           state["batches"][batch_id].get("status") == expected_status


def remediate_batch_state(workflow_state_path, batch_id, status, **kwargs):
    print(f"[WARN] Workflow State NOT UPDATED for {batch_id}, remediate...")
    if status == "generated":
        update_batch_generated(workflow_state_path, batch_id, kwargs.get("batch_size"),
                               kwargs.get("config_path"), kwargs.get("created_at"))
    elif status == "running":
        update_batch_running(workflow_state_path, batch_id, kwargs.get("gpu_pool"),
                             kwargs.get("started_at"))
    elif status == "completed":
        update_batch_completed(workflow_state_path, batch_id, kwargs.get("results_path"),
                               kwargs.get("stats"), kwargs.get("completed_at"))
    print(f"[OK] Remediated: {batch_id} -> {status}")


def run_one_iteration(workflow_state_path, batch_size=50):
    print("=" * 60)
    print("STARTING NEW BATCH ITERATION")
    print("=" * 60)

    gen_result = generate_batch_from_workflow_state(workflow_state_path, batch_size)
    batch_id = gen_result.get("batch_id")
    config_path = gen_result.get("batch_config_path")

    if not check_batch_state(workflow_state_path, batch_id, "generated"):
        remediate_batch_state(workflow_state_path, batch_id, "generated",
                              batch_size=batch_size, config_path=config_path,
                              created_at=datetime.now().isoformat())

    exec_result = execute_batch(Path(config_path), workflow_state_path)

    if not check_batch_state(workflow_state_path, batch_id, "completed"):
        remediate_batch_state(workflow_state_path, batch_id, "completed",
                              results_path=exec_result.get("batch_results_path"),
                              stats=exec_result.get("stats"),
                              completed_at=datetime.now().isoformat())

    state = load_workflow_state(workflow_state_path)
    print(f"\nBatch ID: {batch_id}")
    print(f"Batch Stats: {state.get('batch_stats', {})}")
    print("=" * 60)
    return {"batch_id": batch_id, "stats": exec_result.get("stats")}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-state", required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args()
    workflow_state_path = Path(args.workflow_state)

    for i in range(args.iterations):
        print(f"\nITERATION {i+1}/{args.iterations}")
        run_one_iteration(workflow_state_path, args.batch_size)
        if (i + 1) % 10 == 0:
            print("\n[PAUSE] 10 batches completed. Press Enter...")
            try: input()
            except KeyboardInterrupt: break

    print("\n[DONE]")


if __name__ == "__main__":
    main()