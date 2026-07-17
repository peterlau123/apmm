"""Tests for ut_runner v5 import-only API.

Covers:
  - validate_required_config (8.2)
  - check_gateways_alive via `hermes gateway list` (8.3)
  - apply_pending_config + check_stop_conditions (8.4)
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UT_RUNNER = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "ut_runner.py"


@pytest.fixture(scope="module")
def hr():
    """Import ut_runner.py by file path (hyphenated parent dirs)."""
    # Make `bastion_manager` and `feishu_api` siblings importable
    sys.path.insert(0, str(UT_RUNNER.parent))
    sys.path.insert(0, str(UT_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("ut_runner", UT_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 8.2 validate_required_config ──────────────────────────────────────────────

def test_validate_required_config_missing_test_list_and_manifest(hr):
    cfg = {"config": {"remote_server": "t_h20"}, "input_filter": {}}
    ok, missing = hr.validate_required_config(cfg)
    assert ok is False
    assert any("test_list_path" in m or "manifest_source" in m for m in missing)


def test_validate_required_config_test_list_plus_remote_server_ok(hr):
    cfg = {
        "config": {"remote_server": "t_h20"},
        "input_filter": {"test_list_path": "/tmp/x.txt"},
    }
    ok, missing = hr.validate_required_config(cfg)
    assert ok is True
    assert missing == []


def test_validate_required_config_missing_remote_server(hr):
    cfg = {
        "config": {},
        "input_filter": {"manifest_source": "/tmp/m.json"},
    }
    ok, missing = hr.validate_required_config(cfg)
    assert ok is False
    assert "config.remote_server" in missing


# ── 8.3 check_gateways_alive ──────────────────────────────────────────────────

def test_check_gateways_alive_only_orchestrator(hr):
    stdout = (
        "Gateways:\n"
        "  ✓ ut-batch-selector  — PID 1\n"
        "  ✗ ut-executor      — not running\n"
        "  ✗ ut-fixer         — not running\n"
        "  ✗ ut-manifest-updater — not running\n"
    )
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=stdout)):
        result = hr.check_gateways_alive()

    assert result == {
        "ut-batch-selector": True,
        "ut-executor": False,
        "ut-fixer": False,
        "ut-manifest-updater": False,
    }


def test_check_gateways_alive_missing_hermes_binary(hr):
    """FileNotFoundError (no hermes on PATH) → all False, not raise."""
    with patch("subprocess.run", side_effect=FileNotFoundError("no hermes")):
        assert hr.check_gateways_alive() == {
            "ut-batch-selector": False,
            "ut-executor": False,
            "ut-fixer": False,
            "ut-manifest-updater": False,
        }


# ── 8.4 apply_pending_config + check_stop_conditions ──────────────────────────

def test_apply_pending_config_merges_and_clears(hr, tmp_path):
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps({
        "config": {"batch_size": 8, "remote_server": "t_h20"},
        "pending_config": {"batch_size": 16, "max_retry_per_test": 5},
    }), encoding="utf-8")

    effective = hr.apply_pending_config(state_path)

    assert effective["batch_size"] == 16
    assert effective["max_retry_per_test"] == 5
    assert effective["remote_server"] == "t_h20"

    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["pending_config"] == {}
    assert on_disk["config"]["batch_size"] == 16


def test_apply_pending_config_noop_when_empty(hr, tmp_path):
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps({
        "config": {"batch_size": 8},
        "pending_config": {},
    }), encoding="utf-8")
    effective = hr.apply_pending_config(state_path)
    assert effective["batch_size"] == 8


def test_check_stop_conditions_done(hr, tmp_path):
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps({
        "test_load_stats": {"pending": 0, "running": 0, "passed": 10},
    }), encoding="utf-8")
    done, reason, status = hr.check_stop_conditions(state_path)
    assert done is True
    assert reason == "pending_count == 0"
    assert status == "completed"


def test_check_stop_conditions_not_done_when_pending(hr, tmp_path):
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps({
        "test_load_stats": {"pending": 3, "running": 0},
    }), encoding="utf-8")
    done, reason, status = hr.check_stop_conditions(state_path)
    assert done is False
    assert reason == ""
    assert status == ""


def test_check_stop_conditions_not_done_when_running(hr, tmp_path):
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps({
        "test_load_stats": {"pending": 0, "running": 2},
    }), encoding="utf-8")
    done, _, _ = hr.check_stop_conditions(state_path)
    assert done is False


# ── 2.2 refresh_test_load_stats ────────────────────────────────────────────────

def test_refresh_test_load_stats(hr, tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps({"version": "2.0", "tests": [
        {"test_id": "t1", "status": "passed"},
        {"test_id": "t2", "status": "pending"},
        {"test_id": "t3", "status": "running"}], "statistics": {}}))
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"config": {}}))
    hr.refresh_test_load_stats(sp, mp)
    s = json.loads(sp.read_text())["test_load_stats"]
    assert s["pending"] == 1 and s["running"] == 1 and s["passed"] == 1


# ── 2.1 parse_command (new Command dataclass — see also test_parse_command.py) ─

def test_parse_stop(hr):
    assert hr.parse_command("结束").intent == "stop"


def test_parse_pause(hr):
    assert hr.parse_command("暂停").intent == "pause"


def test_parse_resume(hr):
    assert hr.parse_command("继续").intent == "resume"


def test_parse_otp(hr):
    c = hr.parse_command("123456")
    assert c.intent == "otp" and c.args["code"] == "123456"


def test_parse_change_config(hr):
    c = hr.parse_command("改 batch_size=4")
    assert c.intent == "change_config" and c.args["batch_size"] == "4"


def test_parse_change_config_whitelist_only(hr):
    assert "unknown_key" not in hr.parse_command("改 unknown_key=9").args


def test_parse_non_command(hr):
    assert hr.parse_command("这个测试为什么失败") is None


def test_parse_command_as_dict_back_compat(hr):
    """Legacy {type, payload} adapter still works for archive callers."""
    d = hr.parse_command_as_dict("结束")
    assert d == {"type": "stop", "payload": {}}
    d = hr.parse_command_as_dict("123456")
    assert d == {"type": "otp", "payload": {"code": "123456"}}
