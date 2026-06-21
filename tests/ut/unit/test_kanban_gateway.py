"""Tests for Kanban gateway heartbeat detection.

Task 2.2: Test check_gateways_alive with mock gateway responses.
Uses unittest.mock to simulate systemctl responses.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERMES_RUNNER = PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "hermes_runner.py"


@pytest.fixture(scope="module")
def hr():
    """Import hermes_runner.py by file path."""
    sys.path.insert(0, str(HERMES_RUNNER.parent))
    sys.path.insert(0, str(HERMES_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("hermes_runner", HERMES_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCheckGatewaysAlive:
    """Test gateway heartbeat detection."""

    def test_all_gateways_alive(self, hr):
        """All three gateways are active."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        def mock_run(cmd, **kwargs):
            return mock_result

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is True
        assert result["ut-executor"] is True
        assert result["ut-fixer"] is True

    def test_all_gateways_dead(self, hr):
        """All three gateways are inactive."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        def mock_run(cmd, **kwargs):
            return mock_result

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is False
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False

    def test_partial_gateway_failure(self, hr):
        """Only orchestrator is alive, executor and fixer are dead."""
        def mock_run(cmd, **kwargs):
            mock_result = MagicMock()
            if "ut-orchestrator" in " ".join(cmd):
                mock_result.returncode = 0
            else:
                mock_result.returncode = 1
            return mock_result

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is True
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False

    def test_gateway_timeout(self, hr):
        """Gateway check times out → returns False."""
        import subprocess

        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is False
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False

    def test_gateway_file_not_found_no_systemctl(self, hr):
        """systemctl binary not found (Windows) → returns False."""
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError("systemctl not found")

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is False
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False

    def test_gateway_unexpected_exception(self, hr):
        """Unexpected exception → returns False."""
        def mock_run(cmd, **kwargs):
            raise RuntimeError("unexpected error")

        with patch("subprocess.run", side_effect=mock_run):
            result = hr.check_gateways_alive()

        assert result["ut-orchestrator"] is False
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False


class TestSystemctlActive:
    """Test _systemctl_active helper."""

    def test_active_unit(self, hr):
        """Active unit returns True."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            assert hr._systemctl_active("hermes-gateway@ut-orchestrator") is True

    def test_inactive_unit(self, hr):
        """Inactive unit returns False."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            assert hr._systemctl_active("hermes-gateway@ut-orchestrator") is False

    def test_timeout_returns_false(self, hr):
        """Timeout returns False."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["systemctl"], 5)):
            assert hr._systemctl_active("any-unit") is False

    def test_file_not_found_returns_false(self, hr):
        """FileNotFoundError returns False."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert hr._systemctl_active("any-unit") is False

    def test_generic_exception_returns_false(self, hr):
        """Generic exception returns False."""
        with patch("subprocess.run", side_effect=RuntimeError("oops")):
            assert hr._systemctl_active("any-unit") is False