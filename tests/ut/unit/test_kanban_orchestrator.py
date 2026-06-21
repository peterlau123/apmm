"""Tests for hermes_runner.orchestrator_round (Task 3.1).

orchestrator_round chains REAL v5 Worker functions loaded from hyphenated skill
dirs via importlib:
  - Stage 5: update_manifest (manifest-updater) reconciles prev batch results
  - Stage 2: select_batch + write_batch_config (batch-selector) picks the next batch

Module is loaded via importlib to match the tests/skills/ut/ convention.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERMES_RUNNER = PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "hermes_runner.py"


@pytest.fixture(scope="module")
def hr():
    """Import hermes_runner.py by file path (hyphenated parent dirs)."""
    sys.path.insert(0, str(HERMES_RUNNER.parent))
    sys.path.insert(0, str(HERMES_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("hermes_runner", HERMES_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_orchestrator_round_reconciles_then_selects(hr, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mp = run_dir / "manifest.json"
    mp.write_text(json.dumps({
        "version": "2.0",
        "tests": [
            {"test_id": "t1", "status": "pending", "retry_count": 0, "max_retry": 3, "last_batch_id": None},
            {"test_id": "t2", "status": "pending", "retry_count": 0, "max_retry": 3, "last_batch_id": None},
        ],
        "statistics": {},
    }))
    prev = run_dir / "batch_prev"
    prev.mkdir()
    (prev / "batch_results.json").write_text(json.dumps({
        "batch_id": "batch_prev",
        "tests": [{"test_id": "t1", "status": "passed"}],
    }))

    r = hr.orchestrator_round(
        run_dir=run_dir,
        manifest_path=mp,
        prev_batch_dir=prev,
        batch_size=8,
    )

    m = json.loads(mp.read_text())
    assert next(t for t in m["tests"] if t["test_id"] == "t1")["status"] == "passed"
    assert r["next_batch"]["selected_count"] == 1
    assert r["next_batch"]["tests"][0]["test_id"] == "t2"
    assert r["completed"] is False


def test_orchestrator_round_completed_when_nothing_pending(hr, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mp = run_dir / "manifest.json"
    mp.write_text(json.dumps({
        "version": "2.0",
        "tests": [
            {"test_id": "t1", "status": "passed", "retry_count": 0, "max_retry": 3, "last_batch_id": None},
        ],
        "statistics": {},
    }))

    r = hr.orchestrator_round(
        run_dir=run_dir,
        manifest_path=mp,
        prev_batch_dir=None,
        batch_size=8,
    )

    assert r["completed"] is True
    assert r["next_batch"] is None
