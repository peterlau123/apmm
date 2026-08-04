#!/usr/bin/env python3
"""Tests for workflow_state.json concurrent write safety (file lock).

Regression: 2026-08-04 incident — 8 parallel execute_batch processes
read-modify-write workflow_state.json without locks, corrupting it
(JSONDecodeError: Extra data). Lock must cover both read (LOCK_SH)
and write (LOCK_EX) via a separate .lock file.
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "skills" / "ut" / "ut_common"))

from workflow_state_manager import load_workflow_state, save_workflow_state


def _worker(args):
    path, i = args
    for j in range(30):
        state = load_workflow_state(path)
        state[f"worker_{i}"] = j
        save_workflow_state(state, path)
    return i


class TestWorkflowStateConcurrency:
    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        ws_path = tmp_path / "workflow_state.json"
        save_workflow_state({"workflow": {"status": "running"}, "batches": {}}, ws_path)

        with ProcessPoolExecutor(max_workers=4) as pool:
            list(pool.map(_worker, [(ws_path, i) for i in range(4)]))

        # File must parse cleanly after 4x30 concurrent read-modify-writes
        state = load_workflow_state(ws_path)
        assert state["workflow"]["status"] == "running"
        # At least some worker updates landed (no corruption)
        assert any(f"worker_{i}" in state for i in range(4))

    def test_lock_file_created(self, tmp_path):
        ws_path = tmp_path / "workflow_state.json"
        save_workflow_state({"workflow": {}}, ws_path)
        assert (tmp_path / "workflow_state.json.lock").exists()

    def test_single_write_still_works(self, tmp_path):
        ws_path = tmp_path / "workflow_state.json"
        save_workflow_state({"workflow": {"status": "running"}, "batches": {}}, ws_path)
        state = load_workflow_state(ws_path)
        assert state["workflow"]["status"] == "running"
