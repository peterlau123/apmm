#!/usr/bin/env python3
"""
Tests for two-phase strategy fixes F1-F4.

F1: Phase 1 refreshes test_load stats into workflow_state on completion
F2: Phase 1 transitions workflow_state to phase1_complete / current_stage=phase2
F3: Phase 1 auto-triggers Phase 2 Stage 1
F4: Phase 2 Stage 2 refreshes stats after each retry
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import importlib.util

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# phase2_stage2.py has no __init__.py chain; load via importlib
_p2s2_path = _PROJECT_ROOT / "skills" / "ut" / "ut_common" / "two-phase-handler" / "scripts" / "phase2_stage2.py"
_p2s2_spec = importlib.util.spec_from_file_location("phase2_stage2", _p2s2_path)
_p2s2 = importlib.util.module_from_spec(_p2s2_spec)
_p2s2_spec.loader.exec_module(_p2s2)


class TestF1F2_Phase1StateTransition:
    """F1+F2: _finalize_phase1_state updates workflow_state correctly."""

    def test_refreshes_stats_from_test_load(self, tmp_path):
        """F1: workflow_state.stats should reflect test_load statuses."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        # Setup: test_load with mixed statuses
        test_load = {"tests": [
            {"status": "passed"}, {"status": "passed"},
            {"status": "failed"},
            {"status": "ignored"}, {"status": "ignored"},
            {"status": "error"},
        ]}
        tl_path = tmp_path / "test_load.json"
        tl_path.write_text(json.dumps(test_load))

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {"passed": 0, "failed": 0, "pending": 32933},
            "paths": {"test_load": str(tl_path)},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 2
        assert result["stats"]["failed"] == 1
        assert result["stats"]["ignored"] == 2
        assert result["stats"]["error"] == 1
        assert result["stats"]["pending"] == 0

    def test_transitions_status_to_phase1_complete(self, tmp_path):
        """F2: workflow.status -> phase1_complete, current_stage -> phase2."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": ""},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["workflow"]["status"] == "phase1_complete"
        assert result["current_stage"] == "phase2"

    def test_handles_missing_workflow_state(self, tmp_path):
        """Should not crash if workflow_state.json doesn't exist."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        # Should be a no-op
        _finalize_phase1_state(tmp_path)

    def test_handles_relative_test_load_path(self, tmp_path):
        """test_load path in workflow_state may be relative to run_dir."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        test_load = {"tests": [{"status": "passed"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": "test_load.json"},  # relative
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1


class TestF3_Phase2AutoTrigger:
    """F3: _trigger_phase2_stage1 calls phase2_stage1.py."""

    def test_calls_stage1_script(self, tmp_path):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_run:
            _trigger_phase2_stage1(tmp_path)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "phase2_stage1.py" in args[1]
            assert "--run-dir" in args
            assert str(tmp_path) in args

    def test_handles_missing_script(self, tmp_path, capsys):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("tasks.ut.scripts.auto_run_batches_two_phase._project_root", tmp_path):
            _trigger_phase2_stage1(tmp_path)
            captured = capsys.readouterr()
            assert "not found" in captured.out

    def test_handles_stage1_failure(self, tmp_path, capsys):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="some error")):
            _trigger_phase2_stage1(tmp_path)
            captured = capsys.readouterr()
            assert "failed" in captured.out


class TestF4_Phase2Stage2StatsRefresh:
    """F4: _refresh_stats in phase2_stage2.py updates workflow_state."""

    def test_refreshes_stats_correctly(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [
            {"status": "passed"}, {"status": "passed"}, {"status": "passed"},
            {"status": "failed"},
        ]}
        tl_path = tmp_path / "test_load.json"
        tl_path.write_text(json.dumps(test_load))

        ws = {
            "stats": {"passed": 0, "pending": 4},
            "paths": {"test_load": str(tl_path)},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 3
        assert result["stats"]["failed"] == 1
        assert result["stats"]["pending"] == 0
        assert result["test_load_stats"]["passed"] == 3

    def test_handles_missing_file(self, tmp_path):
        _p2s2._refresh_stats(tmp_path / "nonexistent.json")

    def test_handles_no_test_load_path(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        ws = {"stats": {}, "paths": {}}
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

    def test_handles_relative_path(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [{"status": "passed"}, {"status": "failed"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        ws = {
            "stats": {},
            "paths": {"test_load": "test_load.json"},  # relative
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1
        assert result["stats"]["failed"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
