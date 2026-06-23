"""Tests for the remote bash watchdog (idle + wall-clock timeouts).

Design: tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md §4 + §8 #1.

Coverage:
  - _build_watchdog_script renders all four substitution slots
  - rejects single quotes (would break outer `bash -c '...'` wrap)
  - the pytest log path on remote is `<dir>/<batch_id>/pytest_<batch_id>.log`
  - the second remote call (grep+tail summary) targets the same log filename
  - exit-code 124 path: log surface gets __WATCHDOG__ sentinel
  - batch_results.json records both `timeout` (wall) and `pytest_idle_timeout`
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_DIR = REPO_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


execute_batch_mod = _load("ut_executor_execute_batch_wd", "execute_batch.py")


# ── helpers ────────────────────────────────────────────────────────────────

def _write_batch_config(tmp_path: Path, *, batch_id: str = "batch_20260623_120000"):
    cfg = {
        "batch_id": batch_id,
        "tests": [
            {"id": 1, "test_node": "tests/test_x.py::test_a"},
            {"id": 2, "test_node": "tests/test_x.py::test_b"},
            {"id": 3, "test_node": "tests/test_x.py::test_c"},
        ],
    }
    p = tmp_path / "batch_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _write_workflow_state(tmp_path: Path, *, idle: int = 120, wall: int = 600):
    p = tmp_path / "workflow_state.json"
    p.write_text(json.dumps({
        "paths": {},
        "config": {
            "remote_server": "t_h20",
            "docker_container": "v0.13.0_torch2.5.1_compile",
            "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
            "timeout": wall,
            "pytest_idle_timeout": idle,
        },
    }), encoding="utf-8")
    return p


# ── _build_watchdog_script: pure renderer ──────────────────────────────────

def test_build_watchdog_renders_all_slots():
    script = execute_batch_mod._build_watchdog_script(
        log_path="/r/ut_logs/B/pytest_B.log",
        pytest_full_cmd="cd /vllm && python3 -m pytest -q",
        idle_timeout=120,
        wall_timeout=600,
    )
    assert "/r/ut_logs/B/pytest_B.log" in script
    assert "cd /vllm && python3 -m pytest -q" in script
    assert "120" in script  # idle threshold
    assert "600" in script  # wall threshold
    # Sentinel + kill primitives must be present
    assert "kill -9 $PID" in script
    assert "__WATCHDOG__: wall_clock_exceeded" in script
    assert "__WATCHDOG__: idle_exceeded" in script
    assert "exit 124" in script
    # Idle detection must use stat -c %Y (GNU coreutils)
    assert "stat -c %Y" in script


def test_build_watchdog_rejects_single_quotes_in_cmd():
    """Outer wrap is `bash -c '<script>'`; quoting inside breaks it."""
    with pytest.raises(ValueError):
        execute_batch_mod._build_watchdog_script(
            log_path="/r/foo.log",
            pytest_full_cmd="echo 'hi'",
            idle_timeout=120,
            wall_timeout=600,
        )


def test_build_watchdog_rejects_single_quotes_in_log_path():
    with pytest.raises(ValueError):
        execute_batch_mod._build_watchdog_script(
            log_path="/r/foo's.log",
            pytest_full_cmd="echo hi",
            idle_timeout=120,
            wall_timeout=600,
        )


# ── execute_batch wiring: command + filename + recorded timeouts ───────────

def test_execute_batch_uses_pytest_log_filename(tmp_path):
    """Filename rule §4 D5: <remote_log_dir>/<batch_id>/pytest_<batch_id>.log."""
    cfg = _write_batch_config(tmp_path, batch_id="batch_20260623_120000")
    state = _write_workflow_state(tmp_path)

    captured_cmds: list[str] = []

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        captured_cmds.append(cmd)
        if "pytest" in cmd and "grep" not in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}
        # summary extract
        return {"exit_code": 0, "stdout": "PASSED test_a\n", "stderr": ""}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote):
        execute_batch_mod.execute_batch(cfg, state)

    # First remote call carries the watchdog + pytest invocation.
    pytest_cmd = captured_cmds[0]
    assert "pytest_batch_20260623_120000.log" in pytest_cmd
    assert "raw_log.txt" not in pytest_cmd  # legacy filename gone

    # Watchdog primitives are embedded.
    assert "kill -9" in pytest_cmd
    assert "exit 124" in pytest_cmd

    # Second call grep+tails the SAME filename and includes __WATCHDOG__
    # sentinel in the grep pattern (so the LLM sees it).
    summary_cmd = captured_cmds[1]
    assert "pytest_batch_20260623_120000.log" in summary_cmd
    assert "__WATCHDOG__" in summary_cmd

    # batch_results.json records both timeout values.
    out = json.loads((tmp_path / "batch_results.json").read_text("utf-8"))
    assert out["timeout"] == 600  # wall-clock fallback
    assert out["pytest_idle_timeout"] == 120
    assert out["remote_log"]["raw_log_path"].endswith(
        "/pytest_batch_20260623_120000.log"
    )


def test_execute_batch_passes_idle_and_wall_to_watchdog(tmp_path):
    """Both knobs flow from workflow_state config → watchdog script."""
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path, idle=90, wall=720)

    captured_cmds: list[str] = []

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        captured_cmds.append(cmd)
        if "pytest" in cmd and "grep" not in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote):
        execute_batch_mod.execute_batch(
            cfg, state,
            exec_config={
                "remote_server": "t_h20",
                "docker_container": "v0.13.0_torch2.5.1_compile",
                "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
                "timeout": 720,
                "pytest_idle_timeout": 90,
            },
        )

    pytest_cmd = captured_cmds[0]
    # The thresholds (90 / 720) must appear in the rendered shell script.
    assert " 720 " in pytest_cmd or "$((NOW - START)) -gt 720" in pytest_cmd
    assert " 90 " in pytest_cmd or "$((NOW - LAST_MTIME)) -gt 90" in pytest_cmd


def test_execute_batch_subprocess_timeout_is_wall_plus_buffer(tmp_path):
    """Local agent.py subprocess.run timeout = wall_timeout (run_remote adds
    +60s internally per design §8 #2)."""
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path, idle=120, wall=600)

    captured_kwargs: list[dict] = []

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        captured_kwargs.append({"timeout": timeout, **kwargs})
        if "pytest" in cmd and "grep" not in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote):
        execute_batch_mod.execute_batch(
            cfg, state,
            exec_config={
                "remote_server": "t_h20",
                "docker_container": "v0.13.0_torch2.5.1_compile",
                "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
                "timeout": 600,
                "pytest_idle_timeout": 120,
            },
        )

    # First call (pytest) uses wall_timeout exactly; run_remote internally
    # adds +60s on the subprocess.run side.
    assert captured_kwargs[0]["timeout"] == 600
    # Second call (summary grep) keeps its small 60s budget.
    assert captured_kwargs[1]["timeout"] == 60


def test_execute_batch_defaults_idle_timeout_to_120(tmp_path):
    """Backward-compat: configs without pytest_idle_timeout default to 120s."""
    cfg = _write_batch_config(tmp_path)
    # Write a state WITHOUT pytest_idle_timeout.
    state = tmp_path / "workflow_state.json"
    state.write_text(json.dumps({
        "paths": {},
        "config": {
            "remote_server": "t_h20",
            "docker_container": "v0.13.0_torch2.5.1_compile",
            "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
            "timeout": 600,
            # NOTE: no pytest_idle_timeout
        },
    }), encoding="utf-8")

    captured_cmds: list[str] = []

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        captured_cmds.append(cmd)
        if "pytest" in cmd and "grep" not in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote):
        execute_batch_mod.execute_batch(cfg, state)

    out = json.loads((tmp_path / "batch_results.json").read_text("utf-8"))
    assert out["pytest_idle_timeout"] == 120


def test_watchdog_template_contains_no_single_quotes():
    """Outer wrap is `bash -c '<...>'`. The template must be quote-free so
    the nesting works without escaping gymnastics."""
    assert "'" not in execute_batch_mod.WATCHDOG_TEMPLATE
