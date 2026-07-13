"""Tests for Kanban board functions.

Task 2.2: Additional tests for parse_command and refresh_test_load_stats.
Focuses on edge cases and integration scenarios.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UT_RUNNER = PROJECT_ROOT / "skills" / "ut" / "shared" / "ut_runner.py"


@pytest.fixture(scope="module")
def hr():
    """Import ut_runner.py by file path."""
    sys.path.insert(0, str(UT_RUNNER.parent))
    sys.path.insert(0, str(UT_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("ut_runner", UT_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestParseCommandEdgeCases:
    """Test parse_command with various edge cases."""

    def test_parse_stop_various_keywords(self, hr):
        """All stop keywords should be recognized."""
        for kw in ("结束", "终止", "停止"):
            result = hr.parse_command_as_dict(kw)
            assert result["type"] == "stop"
            assert result["payload"] == {}

    def test_parse_stop_with_extra_text(self, hr):
        """Stop command with extra text requires exact match (Layer 1 regex)."""
        result = hr.parse_command_as_dict("结束")
        assert result["type"] == "stop"

    def test_parse_pause_various_keywords(self, hr):
        """All pause keywords should be recognized."""
        for kw in ("暂停",):
            result = hr.parse_command_as_dict(kw)
            assert result["type"] == "pause"
            assert result["payload"] == {}

    def test_parse_resume_various_keywords(self, hr):
        """All resume keywords should be recognized."""
        for kw in ("继续",):
            result = hr.parse_command_as_dict(kw)
            assert result["type"] == "resume"
            assert result["payload"] == {}

    def test_parse_otp_with_spaces(self, hr):
        """OTP code with leading/trailing spaces."""
        result = hr.parse_command_as_dict("  123456  ")
        assert result["type"] == "otp"
        assert result["payload"]["code"] == "123456"

    def test_parse_otp_invalid_length(self, hr):
        """OTP with invalid length (5 digits) returns None."""
        result = hr.parse_command_as_dict("12345")
        assert result is None

    def test_parse_otp_invalid_format(self, hr):
        """OTP with non-digits returns None."""
        result = hr.parse_command_as_dict("abc123")
        assert result is None

    def test_parse_change_config_multiple_keys(self, hr):
        """Change config with multiple whitelisted keys."""
        result = hr.parse_command_as_dict("改 batch_size=4 pytest_args=-v max_retry_per_test=2 timeout=300")
        assert result["type"] == "change_config"
        assert result["payload"]["batch_size"] == "4"
        assert result["payload"]["pytest_args"] == "-v"
        assert result["payload"]["max_retry_per_test"] == "2"
        assert result["payload"]["timeout"] == "300"

    def test_parse_change_config_mixed_whitelist_non_whitelist(self, hr):
        """Change config with mixed whitelist and non-whitelist keys."""
        result = hr.parse_command_as_dict("改 batch_size=4 unknown_key=9 timeout=300")
        assert result["type"] == "change_config"
        assert "batch_size" in result["payload"]
        assert "timeout" in result["payload"]
        assert "unknown_key" not in result["payload"]

    def test_parse_change_config_empty_payload(self, hr):
        """Change config with only non-whitelisted keys returns empty payload."""
        result = hr.parse_command_as_dict("改 unknown_key=9")
        assert result["type"] == "change_config"
        assert result["payload"] == {}

    def test_parse_empty_string(self, hr):
        """Empty string returns None."""
        result = hr.parse_command_as_dict("")
        assert result is None

    def test_parse_whitespace_only(self, hr):
        """Whitespace only returns None."""
        result = hr.parse_command_as_dict("   ")
        assert result is None

    def test_parse_random_text(self, hr):
        """Random text that doesn't match any pattern returns None."""
        result = hr.parse_command_as_dict("这个测试为什么失败")
        assert result is None

    def test_parse_english_stop_keyword(self, hr):
        """English stop keyword is recognized (regex supports English)."""
        result = hr.parse_command_as_dict("stop")
        assert result["type"] == "stop"


class TestRefreshTestLoadStats:
    """Test refresh_test_load_stats with various manifest states."""

    def test_empty_manifest(self, hr, tmp_path):
        """Empty manifest produces empty stats."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"version": "2.0", "tests": [], "statistics": {}}))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config": {}}))

        stats = hr.refresh_test_load_stats(state_path, manifest_path)
        assert stats == {}

    def test_single_status(self, hr, tmp_path):
        """Manifest with single status type."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": "2.0",
            "tests": [
                {"test_id": "t1", "status": "passed"},
                {"test_id": "t2", "status": "passed"},
                {"test_id": "t3", "status": "passed"},
            ],
            "statistics": {},
        }))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config": {}}))

        stats = hr.refresh_test_load_stats(state_path, manifest_path)
        assert stats["passed"] == 3

    def test_mixed_statuses(self, hr, tmp_path):
        """Manifest with mixed statuses."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": "2.0",
            "tests": [
                {"test_id": "t1", "status": "passed"},
                {"test_id": "t2", "status": "pending"},
                {"test_id": "t3", "status": "running"},
                {"test_id": "t4", "status": "failed"},
                {"test_id": "t5", "status": "error"},
                {"test_id": "t6", "status": "retriable_error"},
            ],
            "statistics": {},
        }))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config": {}}))

        stats = hr.refresh_test_load_stats(state_path, manifest_path)
        assert stats["passed"] == 1
        assert stats["pending"] == 1
        assert stats["running"] == 1
        assert stats["failed"] == 1
        assert stats["error"] == 1
        assert stats["retriable_error"] == 1

    def test_updates_state_file(self, hr, tmp_path):
        """Stats are persisted to state file."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": "2.0",
            "tests": [{"test_id": "t1", "status": "passed"}],
            "statistics": {},
        }))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config": {}, "iteration": 5}))

        hr.refresh_test_load_stats(state_path, manifest_path)

        state = json.loads(state_path.read_text())
        assert state["test_load_stats"]["passed"] == 1
        assert state["iteration"] == 5

    def test_overwrites_previous_stats(self, hr, tmp_path):
        """Previous stats are overwritten."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": "2.0",
            "tests": [{"test_id": "t1", "status": "passed"}],
            "statistics": {},
        }))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({
            "config": {},
            "test_load_stats": {"passed": 99, "pending": 99},
        }))

        hr.refresh_test_load_stats(state_path, manifest_path)

        state = json.loads(state_path.read_text())
        assert state["test_load_stats"]["passed"] == 1
        assert "pending" not in state["test_load_stats"]

    def test_missing_status_key(self, hr, tmp_path):
        """Test entry without status key counts as None status."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": "2.0",
            "tests": [
                {"test_id": "t1", "status": "passed"},
                {"test_id": "t2"},
            ],
            "statistics": {},
        }))
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config": {}}))

        stats = hr.refresh_test_load_stats(state_path, manifest_path)
        assert stats.get(None) == 1
        assert stats["passed"] == 1


class TestGetExecuteConfig:
    """Test get_execute_config flattening."""

    def test_flatten_nested_config(self, hr, tmp_path):
        """Nested config is flattened correctly."""
        state_path = tmp_path / "workflow_state.json"
        state_path.write_text(json.dumps({
            "config": {
                "remote": {
                    "server": "t_h20",
                    "docker": "v0.13.0_torch2.5.1",
                    "vllm_dir": "/gpfs/gcsp/M2.7_verify/vllm",
                },
                "timeout": 600,
                "pytest_args": "-v --tb=long",
                "remote_log_dir": "/gpfs/logs",
            },
        }))

        cfg = hr.get_execute_config(state_path)
        assert cfg["remote_server"] == "t_h20"
        assert cfg["docker_container"] == "v0.13.0_torch2.5.1"
        assert cfg["timeout"] == 600
        assert cfg["pytest_args"] == "-v --tb=long"
        assert cfg["remote_log_dir"] == "/gpfs/logs"

    def test_defaults_when_missing(self, hr, tmp_path):
        """Defaults are used when config keys are missing."""
        state_path = tmp_path / "workflow_state.json"
        state_path.write_text(json.dumps({"config": {"remote": {}}}))

        cfg = hr.get_execute_config(state_path)
        assert cfg["remote_server"] == "t_h20"
        assert cfg["docker_container"] == "v0.13.0_torch2.5.1_compile"
        assert cfg["timeout"] == 600
        assert cfg["pytest_args"] == "-v --tb=long"

    def test_empty_config(self, hr, tmp_path):
        """Empty config returns defaults."""
        state_path = tmp_path / "workflow_state.json"
        state_path.write_text(json.dumps({}))

        cfg = hr.get_execute_config(state_path)
        assert cfg["remote_server"] == "t_h20"
        assert cfg["docker_container"] == "v0.13.0_torch2.5.1_compile"