"""P1 tests — manifest-updater stat audit (Type-B fabrication backstop).

The audit reads ``batch_results.remote_log.raw_log_path`` and runs a remote
``stat -c '%s %Y'`` via tools/agent.py. If the log doesn't exist, is empty,
or its size disagrees materially with the recorded ``size_bytes``,
test_load must NOT be touched.

A transient bastion outage surfaces as a special ``bastion_disconnect:``
reason so the caller can map it to ``next_action=wait`` instead of
``audit_failed``.

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
SCRIPT = REPO_ROOT / "skills" / "ut" / "manifest-updater" / "scripts" / "update_test_load.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("ut_mu_update_test_load", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ut_mu_update_test_load"] = mod
    spec.loader.exec_module(mod)
    return mod


update_test_load_mod = _load()


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
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(1234, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert ok, reason
    assert reason == "ok"


def test_audit_ok_within_tolerance():
    """Late appends (e.g. __WATCHDOG__ sentinel) shouldn't fail the audit."""
    br = _good_batch_results(size=10_000)
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(10_500, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert ok, reason


def test_audit_fails_outside_tolerance():
    """A growth >4 KB beyond recorded size is a real mismatch."""
    br = _good_batch_results(size=10_000)
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(50_000, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert "size_bytes mismatch" in reason


def test_audit_fails_when_log_missing():
    br = _good_batch_results(size=1234)
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(None, None, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert "not found" in reason or "unparseable" in reason


def test_audit_fails_on_empty_remote_log_regardless_of_recorded_size():
    """Fabrication signature: file exists on remote but is empty."""
    br = _good_batch_results(size=1234)
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(0, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert "empty" in reason


def test_audit_fails_when_size_null_and_remote_empty():
    """Schema allows size_bytes=null, but actual file must be non-empty."""
    br = _good_batch_results()
    br["remote_log"]["size_bytes"] = None
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(0, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert "empty" in reason


def test_audit_passes_when_size_null_and_remote_nonempty():
    br = _good_batch_results()
    br["remote_log"]["size_bytes"] = None
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(4242, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert ok, reason


def test_audit_treats_recorded_zero_as_unknown_not_match():
    """`size_bytes: 0` next to a non-empty remote log is NOT a happy path."""
    br = _good_batch_results(size=0)
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(50_000, 1700000000, "")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    # size_bytes==0 falls under "treat as unknown"; non-empty remote passes.
    assert ok, reason


def test_audit_fails_when_raw_log_path_missing():
    br = _good_batch_results()
    br["remote_log"]["raw_log_path"] = ""
    ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert "raw_log_path missing" in reason


def test_audit_surfaces_bastion_disconnect_as_wait_signal():
    """A transient bastion outage MUST NOT be conflated with audit_failed."""
    br = _good_batch_results()
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(None, None,
                                         "bastion disconnect: daemon not reachable")):
        ok, reason = update_test_load_mod.audit_batch_results(br, "t_h20")
    assert not ok
    assert reason.startswith("bastion_disconnect:")


# ── _stat_remote_log: parsing + error tolerance ────────────────────────────


def test_stat_remote_log_parses_size_and_mtime():
    fake = mock.Mock(returncode=0, stdout="4242 1700000000\n", stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime, disc = update_test_load_mod._stat_remote_log("t_h20", "/x/y.log")
    assert size == 4242
    assert mtime == 1700000000
    assert disc == ""


def test_stat_remote_log_tolerates_log_chatter_before_stat_output():
    """agent.py log preambles must NOT hide the real stat result."""
    chatter = (
        "[INFO] connecting to bastion...\n"
        "[INFO] session established\n"
        "4242 1700000000\n"
        "[INFO] disconnect cleanup\n"
    )
    fake = mock.Mock(returncode=0, stdout=chatter, stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime, disc = update_test_load_mod._stat_remote_log("t_h20", "/x/y.log")
    assert size == 4242
    assert mtime == 1700000000


def test_stat_remote_log_returns_none_on_missing_sentinel():
    fake = mock.Mock(returncode=0, stdout="MISSING\n", stderr="")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime, disc = update_test_load_mod._stat_remote_log("t_h20", "/x/y.log")
    assert size is None and mtime is None
    assert disc == ""


def test_stat_remote_log_swallows_timeout_with_disconnect_reason():
    """Timeout is a transient failure — surfaces a non-empty disconnect_reason."""
    import subprocess as _sub
    with mock.patch("subprocess.run",
                    side_effect=_sub.TimeoutExpired(cmd="x", timeout=60)):
        size, mtime, disc = update_test_load_mod._stat_remote_log("t_h20", "/x/y.log")
    assert size is None and mtime is None
    assert disc  # non-empty


def test_stat_remote_log_recognizes_disconnect_signals():
    """When agent.py rc!=0 and stderr mentions a known disconnect token,
    surface that via the disconnect_reason channel."""
    fake = mock.Mock(returncode=1, stdout="",
                     stderr="ssh: connect to host t_h20 port 22: refused")
    with mock.patch("subprocess.run", return_value=fake):
        size, mtime, disc = update_test_load_mod._stat_remote_log("t_h20", "/x/y.log")
    assert size is None
    assert "bastion disconnect" in disc


# ── End-to-end: update_from_workflow_state aborts on audit failure ─────────


def _seed_workflow_state(tmp_path, test_load_before):
    """Build a workflow_state.json + test_load + empty batch dir."""
    state_path = tmp_path / "workflow_state.json"
    test_load_path = tmp_path / "test_load.json"
    batches_dir = tmp_path / "batches"
    batch_id = "batch_20260623_120000"
    batch_dir = batches_dir / batch_id
    batch_dir.mkdir(parents=True)

    state_path.write_text(json.dumps({
        "paths": {
            "test_load": str(test_load_path),
            "batches_dir": str(batches_dir),
        },
        "current_batch": {"batch_id": batch_id},
        "config": {"remote_server": "t_h20"},
    }), encoding="utf-8")
    test_load_path.write_text(json.dumps(test_load_before), encoding="utf-8")
    return state_path, test_load_path, batch_dir


def test_update_from_workflow_state_aborts_on_audit_failure(tmp_path):
    """Critical: when audit fails (non-disconnect), test_load must NOT be
    mutated and the error verdict must NOT be a wait signal."""
    test_load_before = {
        "version": "1.0",
        "tests": [
            {"test_id": 1, "test_node": "tests/test_x.py::test_a",
             "status": "pending"},
        ],
        "statistics": {"total": 1, "pending": 1},
    }
    state_path, test_load_path, batch_dir = _seed_workflow_state(
        tmp_path, test_load_before
    )

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
    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(None, None, "")):
        result = update_test_load_mod.update_from_workflow_state(state_path)

    assert result.get("error") == "audit_failed"
    assert "reason" in result
    assert "next_action" not in result  # NOT a wait signal

    # test_load must be untouched.
    test_load_after = json.loads(test_load_path.read_text(encoding="utf-8"))
    assert test_load_after["tests"][0]["status"] == "pending"


def test_update_from_workflow_state_returns_wait_on_bastion_disconnect(tmp_path):
    """A bastion disconnect during the audit must map to next_action=wait,
    NOT audit_failed — the supervisor's reconnect loop owns the recovery."""
    test_load_before = {
        "version": "1.0",
        "tests": [
            {"test_id": 1, "test_node": "tests/test_x.py::test_a",
             "status": "pending"},
        ],
        "statistics": {"total": 1, "pending": 1},
    }
    state_path, test_load_path, batch_dir = _seed_workflow_state(
        tmp_path, test_load_before
    )
    (batch_dir / "batch_results.json").write_text(
        json.dumps(_good_batch_results()), encoding="utf-8"
    )

    with mock.patch.object(update_test_load_mod, "_stat_remote_log",
                           return_value=(None, None,
                                         "bastion disconnect: daemon not reachable")):
        result = update_test_load_mod.update_from_workflow_state(state_path)

    assert result.get("next_action") == "wait"
    assert "audit_failed" not in (result.get("error") or "")

    test_load_after = json.loads(test_load_path.read_text(encoding="utf-8"))
    assert test_load_after["tests"][0]["status"] == "pending"
