"""Tests for Kanban gateway liveness detection.

check_gateways_alive() probes `hermes gateway list` (cross-platform) and marks
a profile alive when its line carries the ✓ marker.
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERMES_RUNNER = PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "hermes_runner.py"


@pytest.fixture(scope="module")
def hr():
    """Import hermes_runner.py by file path."""
    sys.path.insert(0, str(HERMES_RUNNER.parent))
    sys.path.insert(0, str(HERMES_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("hermes_runner", HERMES_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _list_result(stdout, returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    return r


# Representative `hermes gateway list` output lines.
_ALL_ALIVE = (
    "Gateways:\n"
    "  ✓ ut-batch-selector       — PID 24096\n"
    "  ✓ ut-executor              — PID 53076\n"
    "  ✓ ut-fixer (current)       — PID 39792\n"
    "  ✓ ut-manifest-updater      — PID 12345\n"
    "  ✗ ut-supervisor            — not running\n"
)
_PARTIAL = (
    "Gateways:\n"
    "  ✓ ut-batch-selector       — PID 24096\n"
    "  ✗ ut-executor              — not running\n"
    "  ✗ ut-fixer                 — not running\n"
    "  ✗ ut-manifest-updater      — not running\n"
)
_ALL_DEAD = (
    "Gateways:\n"
    "  ✗ ut-batch-selector        — not running\n"
    "  ✗ ut-executor              — not running\n"
    "  ✗ ut-fixer                 — not running\n"
    "  ✗ ut-manifest-updater      — not running\n"
)


class TestCheckGatewaysAlive:
    """Test gateway liveness detection via `hermes gateway list`."""

    def test_all_gateways_alive(self, hr):
        with patch("subprocess.run", return_value=_list_result(_ALL_ALIVE)):
            result = hr.check_gateways_alive()
        assert result["ut-batch-selector"] is True
        assert result["ut-executor"] is True
        assert result["ut-fixer"] is True
        assert result["ut-manifest-updater"] is True

    def test_all_gateways_dead(self, hr):
        """Lines present but marked ✗ (not running) → all False."""
        with patch("subprocess.run", return_value=_list_result(_ALL_DEAD)):
            result = hr.check_gateways_alive()
        assert result["ut-batch-selector"] is False
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False
        assert result["ut-manifest-updater"] is False

    def test_partial_gateway_failure(self, hr):
        """Only batch-selector carries ✓."""
        with patch("subprocess.run", return_value=_list_result(_PARTIAL)):
            result = hr.check_gateways_alive()
        assert result["ut-batch-selector"] is True
        assert result["ut-executor"] is False
        assert result["ut-fixer"] is False
        assert result["ut-manifest-updater"] is False

    def test_nonzero_returncode(self, hr):
        """`hermes gateway list` failing → all False."""
        with patch("subprocess.run", return_value=_list_result("", returncode=1)):
            result = hr.check_gateways_alive()
        assert all(v is False for v in result.values())

    def test_gateway_timeout(self, hr):
        """Probe times out → all False."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["hermes"], 15)):
            result = hr.check_gateways_alive()
        assert all(v is False for v in result.values())

    def test_hermes_binary_not_found(self, hr):
        """`hermes` not on PATH → all False."""
        with patch("subprocess.run", side_effect=FileNotFoundError("hermes not found")):
            result = hr.check_gateways_alive()
        assert all(v is False for v in result.values())
