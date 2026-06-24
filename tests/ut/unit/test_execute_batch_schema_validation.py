"""Strict-schema validation tests for execute_batch.py (P0b).

Type-B fabrication defense: any drift in the executor's batch_results.json
payload (or a hand-rolled LLM substitute) must fail LOUD via jsonschema
validation BEFORE the file lands on disk.

These tests exercise the validator directly via the module's private helper
``_validate_batch_results_or_raise`` and check both the happy path and several
realistic drift patterns observed in the 2026-06-23 fabricated run.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_DIR = REPO_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


execute_batch_mod = _load("ut_executor_execute_batch_schema", "execute_batch.py")


def _good_payload() -> dict:
    """Canonical v5 batch_results payload (passes schema)."""
    return {
        "batch_id": "batch_20260623_120000",
        "started_at": "2026-06-23T12:00:00Z",
        "finished_at": "2026-06-23T12:10:00Z",
        "timeout": 600,
        "pytest_idle_timeout": 120,
        "exit_code": 0,
        "remote_log": {
            "host": "t_h20",
            "container": "v0.13.0_torch2.5.1_compile",
            "raw_log_path": "/gpfs/x/ut_logs/B/pytest_batch_20260623_120000.log",
            "size_bytes": 1234,
            "captured_at": "2026-06-23T12:10:01Z",
        },
        "tests": [
            {
                "id": 1,
                "test_node": "tests/test_x.py::test_a",
                "status": "passed",
                "error_type": None,
                "duration_ms": 0,
            }
        ],
        "statistics": {"total": 1, "passed": 1, "failed": 0, "error": 0},
    }


# ── Happy path ─────────────────────────────────────────────────────────────


def test_canonical_payload_validates():
    execute_batch_mod._validate_batch_results_or_raise(_good_payload())


# ── Type-B drift patterns from ut-20260623-223710 ──────────────────────────


def test_legacy_executed_at_field_rejected():
    """Pre-v5 hand-written payloads used ``executed_at`` instead of
    ``started_at``+``finished_at``. additionalProperties:false must catch it."""
    p = _good_payload()
    del p["started_at"]
    p["executed_at"] = "2026-06-23T12:00:00Z"
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_legacy_total_duration_seconds_field_rejected():
    p = _good_payload()
    p["total_duration_seconds"] = 620
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_legacy_stats_key_rejected_when_statistics_required():
    """Old schema used ``stats``; v5 requires ``statistics``."""
    p = _good_payload()
    p["stats"] = p.pop("statistics")
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


# ── Field-level validation ─────────────────────────────────────────────────


def test_missing_remote_log_rejected():
    p = _good_payload()
    del p["remote_log"]
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_raw_log_path_must_use_pytest_prefix():
    """Filename rule §4 D5: pytest_<batch_id>.log; legacy raw_log.txt rejected."""
    p = _good_payload()
    p["remote_log"]["raw_log_path"] = "/gpfs/x/ut_logs/B/raw_log.txt"
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_started_at_must_be_utc_z():
    """Local-time / offset timestamps rejected; only ISO 8601 UTC Z."""
    p = _good_payload()
    p["started_at"] = "2026-06-23T12:00:00+08:00"
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_unknown_status_rejected():
    p = _good_payload()
    p["tests"][0]["status"] = "fabricated"
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


def test_retriable_error_status_accepted():
    """Watchdog timeouts set status=retriable_error, error_type=timeout."""
    p = _good_payload()
    p["tests"][0]["status"] = "retriable_error"
    p["tests"][0]["error_type"] = "timeout"
    p["statistics"]["retriable_error"] = 1
    execute_batch_mod._validate_batch_results_or_raise(p)


def test_additional_top_level_field_rejected():
    """``additionalProperties: false`` must catch any drift field."""
    p = _good_payload()
    p["fabricated_extra"] = "lol"
    with pytest.raises(ValueError, match=r"violates schema"):
        execute_batch_mod._validate_batch_results_or_raise(p)


# ── End-to-end: execute_batch refuses to write on validation failure ──────


def test_execute_batch_blocks_write_on_schema_violation(tmp_path):
    """If we corrupt the payload at the last moment, output_path must NOT be
    written. Instead the executor returns a structured wait verdict and
    quarantines the rejected payload (P2 SKILL.md HARD CONTRACT — never raise
    a bare ValueError out of execute_batch; always return next_action shape)."""
    from unittest import mock

    cfg = tmp_path / "batch_config.json"
    cfg.write_text(json.dumps({
        "batch_id": "batch_p1_r1_w1_test",
        "tests": [{"id": 1, "test_node": "tests/test_x.py::test_a"}],
    }), encoding="utf-8")
    state = tmp_path / "workflow_state.json"
    state.write_text(json.dumps({
        "paths": {},
        "config": {
            "remote_server": "t_h20",
            "docker_container": "v0.13.0_torch2.5.1_compile",
            "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
        },
    }), encoding="utf-8")

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        return {"exit_code": 0,
                "stdout": ("PASSED tests/test_x.py::test_a\n"
                           "__REMOTE_LOG_SIZE__4242\n"),
                "stderr": "", "size_bytes": 100}

    orig_validate = execute_batch_mod._validate_batch_results_or_raise

    def corrupting_validate(payload):
        payload["__rogue__"] = True  # additionalProperties:false → raises
        orig_validate(payload)

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote), \
         mock.patch.object(execute_batch_mod,
                           "_validate_batch_results_or_raise",
                           side_effect=corrupting_validate):
        result = execute_batch_mod.execute_batch(cfg, state)

    # Structured wait verdict, no bare ValueError.
    assert result.get("next_action") == "wait"
    assert "schema_validation_failed" in (result.get("reason") or "")
    # batch_results.json NOT written (the canonical path).
    assert not (tmp_path / "batch_results.json").exists(), \
        "execute_batch wrote batch_results.json despite schema validation failure"
    # Quarantine artefact IS written so a human can diff it.
    assert (tmp_path / "batch_results.rejected.json").exists()


# ── Real-remote-size sentinel parsing (fix #1 from code review) ─────────────


def test_remote_log_size_sentinel_is_parsed_and_excluded_from_summary():
    """The executor piggy-backs `stat -c %s` on the summary call via a
    __REMOTE_LOG_SIZE__N sentinel line. The sentinel MUST be stripped from
    the local summary.txt and become the recorded remote_log.size_bytes."""
    stdout_blob = (
        "PASSED tests/test_x.py::test_a\n"
        "PASSED tests/test_x.py::test_b\n"
        "----\n"
        "tail line 1\n"
        "tail line 2\n"
        "__REMOTE_LOG_SIZE__50000\n"
    )
    summary, size = execute_batch_mod._split_remote_log_size(stdout_blob)
    assert size == 50000
    assert "__REMOTE_LOG_SIZE__" not in summary
    assert "PASSED tests/test_x.py::test_a" in summary


def test_remote_log_size_sentinel_zero_treated_as_unknown():
    """`stat -c %s` returns 0 only when the OR'd `echo 0` fallback triggered
    (file missing). Zero must NOT be recorded as a literal size_bytes=0."""
    stdout_blob = "PASSED tests/test_x.py::test_a\n__REMOTE_LOG_SIZE__0\n"
    summary, size = execute_batch_mod._split_remote_log_size(stdout_blob)
    assert size is None
    assert "__REMOTE_LOG_SIZE__" not in summary


def test_remote_log_size_sentinel_absent_returns_none():
    stdout_blob = "PASSED tests/test_x.py::test_a\n"
    summary, size = execute_batch_mod._split_remote_log_size(stdout_blob)
    assert size is None
    assert summary == stdout_blob
