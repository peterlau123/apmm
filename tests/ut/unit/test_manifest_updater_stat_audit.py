"""P1 tests — manifest-updater stat audit (Type-B fabrication backstop).

The audit reads ``batch_results.remote_log.raw_log_path`` and runs a remote
``stat -c '%s %Y'`` via tools/agent.py. If the log doesn't exist or its size
disagrees with the recorded ``size_bytes``, manifest.json must NOT be touched.

See post-mortem ut-20260623-223710 for the fabrication signature this guards
against: the worker LLM wrote a plausible-looking batch_results.json without
ever running pytest, leaving a remote log that was either absent or empty.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "ut" / "manifest-updater" / "scripts" / "update_status.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("ut_mu_update_status", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ut_mu_update_status"] = mod
    spec.loader.exec_module(mod)
    return mod


update_status = _load()


def _good_batch_results(size: int = 1234) -> dict:
    return {
        "batch_id": "batch_20260623_120000",
        "started_at": "2026-06-23T12:00:00Z",
        "finished_at": "2026-06-23T12:10:00Z",
        "exit_code": 0,
        "remote_log": {
            "host": "t_h20",
            "container": "v0.13.0_torch2.5.1_compile",
            "raw_log_path": "/gpfs/x/ut_logs/B/pytest_batch_20260623_120000.log",
            "size_bytes": size,
            "captured_at": "2026-06-23T12:10:01Z",
        },
        "tests": [],
        "statistics": {"total": 0, "passed": 0, "failed": 0, "error": 0},
    }


# ── audit_batch_results: pure logic ────────────────────────────────────────


def test_audit_ok_when_size_matches():
    br = _good_batch_results(size=1234)
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(1234, 1700000000)):
        ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert ok, reason
    assert reason == "ok"


def test_audit_fails_when_log_missing():
    br = _good_batch_results(size=1234)
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(None, None)):
        ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert not ok
    assert "not found" in reason or "stat failed" in reason


def test_audit_fails_on_size_mismatch():
    """Fabrication signature: recorded says 1234, truth says 0."""
    br = _good_batch_results(size=1234)
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(0, 1700000000)):
        ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert not ok
    assert "size_bytes mismatch" in reason


def test_audit_fails_when_size_null_and_remote_empty():
    """Schema allows size_bytes=null, but actual file must be non-empty."""
    br = _good_batch_results()
    br["remote_log"]["size_bytes"] = None
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(0, 1700000000)):
        ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert not ok
    assert "empty" in reason


def test_audit_passes_when_size_null_and_remote_nonempty():
    br = _good_batch_results()
    br["remote_log"]["size_bytes"] = None
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(4242, 1700000000)):
        ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert ok, reason


def test_audit_fails_when_raw_log_path_missing():
    br = _good_batch_results()
    br["remote_log"]["raw_log_path"] = ""
    ok, reason = update_status.audit_batch_results(br, "t_h20")
    assert not ok
    assert "raw_log_path missing" in reason


# ── _stat_remote_log: parsing + error tolerance ────────────────────────────


def test_stat_remote_log_parses_size_and_mtime():
    fake = mock.Mock(returncode=0, stdout="4242 1700000000\n", stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime = update_status._stat_remote_log("t_h20", "/x/y.log")
    assert size == 4242
    assert mtime == 1700000000


def test_stat_remote_log_returns_none_on_missing_sentinel():
    fake = mock.Mock(returncode=0, stdout="MISSING\n", stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime = update_status._stat_remote_log("t_h20", "/x/y.log")
    assert size is None and mtime is None


def test_stat_remote_log_swallows_timeout():
    """Audit must never raise — timeouts return (None, None) for caller."""
    import subprocess as _sub
    with mock.patch("subprocess.run",
                    side_effect=_sub.TimeoutExpired(cmd="x", timeout=60)):
        size, mtime = update_status._stat_remote_log("t_h20", "/x/y.log")
    assert size is None and mtime is None


# ── End-to-end: update_from_workflow_state aborts on audit failure ─────────


def test_update_from_workflow_state_aborts_on_audit_failure(tmp_path):
    """Critical: when audit fails, manifest.json must NOT be mutated."""
    state_path = tmp_path / "workflow_state.json"
    manifest_path = tmp_path / "manifest.json"
    batches_dir = tmp_path / "batches"
    batch_id = "batch_20260623_120000"
    batch_dir = batches_dir / batch_id
    batch_dir.mkdir(parents=True)

    state_path.write_text(json.dumps({
        "paths": {
            "manifest": str(manifest_path),
            "batches_dir": str(batches_dir),
        },
        "current_batch": {"batch_id": batch_id},
        "config": {"remote_server": "t_h20"},
    }), encoding="utf-8")

    manifest_before = {
        "version": "1.0",
        "tests": [
            {"test_id": 1, "test_node": "tests/test_x.py::test_a",
             "status": "pending"},
        ],
        "statistics": {"total": 1, "pending": 1},
    }
    manifest_path.write_text(json.dumps(manifest_before), encoding="utf-8")

    # Fabricated batch_results: claims passed but log will fail audit.
    fabricated = _good_batch_results()
    fabricated["tests"] = [{
        "id": 1, "test_node": "tests/test_x.py::test_a",
        "status": "passed", "error_type": None, "duration_ms": 0,
    }]
    fabricated["statistics"] = {"total": 1, "passed": 1, "failed": 0, "error": 0}
    (batch_dir / "batch_results.json").write_text(
        json.dumps(fabricated), encoding="utf-8"
    )

    # Force audit to fail — simulate "remote log not found".
    with mock.patch.object(update_status, "_stat_remote_log",
                           return_value=(None, None)):
        result = update_status.update_from_workflow_state(state_path)

    assert result.get("error") == "audit_failed"
    assert "reason" in result

    # Manifest must be untouched.
    manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    # `pending` status preserved, no flip to passed.
    assert manifest_after["tests"][0]["status"] == "pending"
