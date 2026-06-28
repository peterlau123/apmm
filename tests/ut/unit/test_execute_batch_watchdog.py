"""Tests for the simplified per-test remote bash script (no watchdog loop).

Design: tasks/ut/docs/designs/2026-06-24-executor-parallel-gpu.md §10 P0 fix.

v6 simplified watchdog (from previous setsid+PGID version):
  - Removed setsid + & + PGID + watchdog loop (buggy semantics).
  - Simplified to synchronous bash execution.
  - Timeout managed by outer run_remote(timeout=wall_timeout).
  - Zombie cleanup handled by GPU zombie cleaner at batch startup (§4.1).

Coverage:
  - _build_watchdog_script renders log_path / pytest_full_cmd
  - rejects single quotes (would break outer wrap)
  - no idle / stat -c %Y / setsid / PGID / watchdog loop primitives
  - execute_batch sends single-line `sudo -n docker exec` cmds (post-mortem
    ut-20260623-223710 regression guard still applies)
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


def _write_workflow_state(tmp_path: Path, *, wall: int = 300):
    p = tmp_path / "workflow_state.json"
    p.write_text(json.dumps({
        "paths": {},
        "config": {
            "remote_server": "t_h20",
            "docker_container": "v0.13.0_torch2.5.1_compile",
            "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
            "timeout": wall,
        },
    }), encoding="utf-8")
    return p


def _decode_b64_cmd(wrapped_cmd: str) -> str:
    """Pull the base64 payload out of a `_wrap_with_docker_exec_b64` cmd and
    return the inner script as text."""
    import base64 as _b64, re as _re
    m = _re.search(r"echo (\S+) \| base64 -d", wrapped_cmd)
    assert m, f"not a b64-wrapped docker cmd: {wrapped_cmd[:120]!r}"
    return _b64.b64decode(m.group(1)).decode("utf-8")


_PASSING_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<testsuites><testsuite name="t">'
    '<testcase classname="c" name="n" time="0.5">'
    '</testcase></testsuite></testsuites>'
)


# ── _build_watchdog_script: pure renderer ──────────────────────────────────

def test_build_watchdog_renders_all_slots():
    script = execute_batch_mod._build_watchdog_script(
        log_path="/r/ut_logs/B/pytest_B.log",
        pytest_full_cmd="cd /vllm && python3 -m pytest -q",
    )
    assert "/r/ut_logs/B/pytest_B.log" in script
    assert "cd /vllm && python3 -m pytest -q" in script
    # Simplified: no setsid / PGID / watchdog loop / exit 124
    assert "setsid" not in script
    assert "kill -- -$PGID" not in script
    assert "__WATCHDOG__" not in script
    assert "exit 124" not in script
    assert "mkdir -p" in script  # directory creation still present


def test_build_watchdog_wall_only_no_idle_primitives():
    """G2: idle/mtime heuristic deleted. No stat -c %Y, no idle sentinel."""
    script = execute_batch_mod._build_watchdog_script(
        log_path="/r/foo.log",
        pytest_full_cmd="python3 -m pytest x",
    )
    assert "stat -c %Y" not in script
    assert "idle_exceeded" not in script
    assert "LAST_MTIME" not in script
    # Also no watchdog loop primitives
    assert "while kill -0" not in script
    assert "PID=$!" not in script


def test_build_watchdog_rejects_single_quotes_in_cmd():
    with pytest.raises(ValueError):
        execute_batch_mod._build_watchdog_script(
            log_path="/r/foo.log",
            pytest_full_cmd="echo 'hi'",
        )


def test_build_watchdog_rejects_single_quotes_in_log_path():
    with pytest.raises(ValueError):
        execute_batch_mod._build_watchdog_script(
            log_path="/r/foo's.log",
            pytest_full_cmd="echo hi",
        )


def test_watchdog_template_contains_no_single_quotes():
    """Outer wrap is `bash -c '<...>'`. The template must be quote-free."""
    assert "'" not in execute_batch_mod.WATCHDOG_TEMPLATE


# ── execute_batch wiring ────────────────────────────────────────────────────

def test_execute_batch_pytest_cmd_is_single_line_and_uses_sudo_n(tmp_path):
    """End-to-end: every cmd execute_batch sends to run_remote is single-line
    and `sudo -n` — post-mortem ut-20260623-223710 regression guard."""
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path)

    captured_cmds: list[str] = []

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        captured_cmds.append(cmd)
        inner = _decode_b64_cmd(cmd)
        if "cat " in inner:  # fetch call
            return {"exit_code": 0, "stdout": _PASSING_XML, "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote), \
         mock.patch.object(execute_batch_mod, "_detect_free_gpus",
                           return_value=([0, 1], 0)):
        execute_batch_mod.execute_batch(cfg, state)

    assert captured_cmds, "no remote cmds captured"
    for i, cmd in enumerate(captured_cmds):
        assert "\n" not in cmd, f"cmd #{i} has bare newline: {cmd[:200]!r}"
        assert cmd.startswith("sudo -n docker exec "), (
            f"cmd #{i} must start with `sudo -n docker exec`: {cmd[:120]!r}"
        )


def test_execute_batch_passes_per_test_wall_to_run_remote(tmp_path):
    """wall_timeout (config `timeout`) flows into run_remote as timeout argument.

    Previously it went into watchdog script; now simplified watchdog has no
    timeout loop, so run_remote manages the timeout directly."""
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path, wall=300)

    pytest_timeout = None
    fetch_timeout = None

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        nonlocal pytest_timeout, fetch_timeout
        inner = _decode_b64_cmd(cmd)
        # Distinguish pytest execution vs fetch by checking inner script
        if "cat " in inner:  # fetch call
            fetch_timeout = timeout
            return {"exit_code": 0, "stdout": _PASSING_XML, "stderr": ""}
        else:  # pytest execution (watchdog script)
            pytest_timeout = timeout
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote), \
         mock.patch.object(execute_batch_mod, "_detect_free_gpus",
                           return_value=([0], 0)):
        execute_batch_mod.execute_batch(cfg, state)

    # wall_timeout flows to pytest execution run_remote
    assert pytest_timeout == 300
    # fetch uses separate timeout (60s)
    assert fetch_timeout == 60

    out = json.loads((tmp_path / "batch_results.json").read_text("utf-8"))
    assert out["timeout"] == 300


def test_execute_batch_records_per_node_log_and_xml_paths(tmp_path):
    """Each test entry carries its per-node log_path + xml_path (schema v6)."""
    cfg = _write_batch_config(tmp_path, batch_id="batch_20260624_010000")
    state = _write_workflow_state(tmp_path)

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        inner = _decode_b64_cmd(cmd)
        if "cat " in inner:
            return {"exit_code": 0, "stdout": _PASSING_XML, "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote), \
         mock.patch.object(execute_batch_mod, "_detect_free_gpus",
                           return_value=([0], 0)):
        execute_batch_mod.execute_batch(cfg, state)

    out = json.loads((tmp_path / "batch_results.json").read_text("utf-8"))
    for entry in out["tests"]:
        assert entry["log_path"].startswith(
            "/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260624_010000/pytest_"
        )
        assert entry["xml_path"].startswith(
            "/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260624_010000/result_"
        )
        assert entry["gpu_id"] == 0
        assert entry["status"] == "passed"


# ── Post-mortem regression (ut-20260623-223710): docker exec wrapping ──────

def test_docker_wrap_uses_sudo_dash_n():
    cmd = execute_batch_mod._wrap_with_docker_exec_b64(
        "v0.13.0_torch2.5.1_compile", "echo hi"
    )
    assert cmd.startswith("sudo -n docker exec ")
    assert "sudo docker" not in cmd


def test_docker_wrap_has_no_bare_newlines():
    multiline_script = (
        "mkdir -p /tmp/x\n"
        "( cd /vllm && python3 -m pytest tests/test_a.py ) > /tmp/x/log 2>&1 &\n"
        "PID=$!\n"
        "wait $PID\n"
    )
    cmd = execute_batch_mod._wrap_with_docker_exec_b64("C", multiline_script)
    assert "\n" not in cmd


def test_docker_wrap_payload_is_pure_ascii_no_quoting_hazard():
    inner = "echo 'hello \"world\"' && grep -E '(A|B)' /tmp/foo.log"
    cmd = execute_batch_mod._wrap_with_docker_exec_b64("C", inner)
    assert "base64 -d" in cmd
    assert cmd.count("'") == 0
    import base64 as _b64, re as _re
    m = _re.search(r"echo (\S+) \| base64 -d", cmd)
    assert m
    assert _b64.b64decode(m.group(1)).decode("utf-8") == inner


# ── env_vars injection tests (Task 2 code review fix) ─────────────────────────

def test_docker_wrap_includes_env_flags():
    """env_vars dict flows into the docker exec command as -e VAR=VALUE flags."""
    cmd = execute_batch_mod._wrap_with_docker_exec_b64(
        "container", "echo hi",
        env_vars={"HF_HOME": "/path/to/cache", "HF_HUB_OFFLINE": "1"}
    )
    assert " -e HF_HOME=/path/to/cache" in cmd
    assert " -e HF_HUB_OFFLINE=1" in cmd


def test_docker_wrap_rejects_env_value_with_spaces():
    """Values containing spaces are rejected to prevent shell injection."""
    with pytest.raises(ValueError) as exc_info:
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"HF_HOME": "/path with spaces"}
        )
    assert "HF_HOME" in str(exc_info.value)
    assert "spaces" in str(exc_info.value)


def test_docker_wrap_rejects_env_value_with_shell_metacharacters():
    """Values containing shell metacharacters are rejected."""
    # Test $ metacharacter
    with pytest.raises(ValueError) as exc_info:
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"VAR": "$HOME"}
        )
    assert "VAR" in str(exc_info.value)

    # Test ; metacharacter
    with pytest.raises(ValueError):
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"VAR": "value;rm -rf /"}
        )

    # Test | metacharacter
    with pytest.raises(ValueError):
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"VAR": "a|b"}
        )

    # Test single quote
    with pytest.raises(ValueError):
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"VAR": "val'ue"}
        )

    # Test double quote
    with pytest.raises(ValueError):
        execute_batch_mod._wrap_with_docker_exec_b64(
            "container", "echo hi",
            env_vars={"VAR": "val\"ue"}
        )


def test_docker_wrap_accepts_safe_env_values():
    """Safe values (paths, numbers, flags) pass validation."""
    cmd = execute_batch_mod._wrap_with_docker_exec_b64(
        "container", "echo hi",
        env_vars={
            "HF_HOME": "/gpfs/cache/hf",
            "CUDA_VISIBLE_DEVICES": "0,1,2",
            "HF_HUB_OFFLINE": "1",
            "MAX_WORKERS": "4",
        }
    )
    assert " -e HF_HOME=/gpfs/cache/hf" in cmd
    assert " -e CUDA_VISIBLE_DEVICES=0,1,2" in cmd
    assert " -e HF_HUB_OFFLINE=1" in cmd
    assert " -e MAX_WORKERS=4" in cmd
