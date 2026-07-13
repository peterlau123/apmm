#!/usr/bin/env python3
"""
verify_batch_checkpoint.py - Two-phase checkpoint verification

Verifies that test_load was updated for a given batch. Used as the two-phase
mode alternative to the linear/kanban stat audit (audit_batch_results).

Usage:
    python verify_batch_checkpoint.py \
        --workflow-state runs/ut-20260708/workflow_state.json \
        --batch-id batch_20260708_130000

Exit codes:
    0 - verification passed (test_load updated for this batch)
    1 - verification failed (test_load NOT updated)
    2 - error (workflow_state or test_load not found)
"""

import argparse
import json
import sys
from pathlib import Path


def verify_batch_updated(batch_id: str, workflow_state_path: Path) -> bool:
    """Checkpoint verification: Verify test_load was updated for batch.

    Reads test_load path from workflow_state.json, then checks if any test
    has this batch_id with updated status (non-pending).

    Standalone version of the inline function in auto_run_batches_two_phase.py.
    """
    try:
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        paths = state.get("paths", {})
        test_load_path = paths.get("test_load", "")
        if not test_load_path or not Path(test_load_path).exists():
            return False
        test_load = json.loads(Path(test_load_path).read_text(encoding="utf-8"))
        for test in test_load.get("tests", []):
            if test.get("last_batch_id") == batch_id:
                if test.get("status", "pending") != "pending":
                    return True
        return False
    except (json.JSONDecodeError, Exception):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Two-phase checkpoint: verify test_load was updated for a batch"
    )
    parser.add_argument("--workflow-state", required=True, help="workflow_state.json path")
    parser.add_argument("--batch-id", required=True, help="Batch ID to verify")
    args = parser.parse_args()

    workflow_state_path = Path(args.workflow_state)
    if not workflow_state_path.exists():
        print(json.dumps({"verified": False, "error": f"workflow_state.json not found: {workflow_state_path}"}, indent=2))
        return 2

    ok = verify_batch_updated(args.batch_id, workflow_state_path)
    result = {"verified": ok, "batch_id": args.batch_id, "workflow_state": str(workflow_state_path)}
    if ok:
        result["message"] = f"Checkpoint PASSED: test_load updated for {args.batch_id}"
        print(json.dumps(result, indent=2))
        return 0
    else:
        result["message"] = f"Checkpoint FAILED: test_load NOT updated for {args.batch_id}"
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
