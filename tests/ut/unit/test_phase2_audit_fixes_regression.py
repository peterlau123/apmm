"""Regression tests for the 2026-07-17 single/two-phase audit fixes.

F1: phase2_stage1.py classify() must count `ignored` status (refactor regression).
F2: phase2_stage1.py main() must NOT fall back to all-non-pending for an empty batch dir.
F5: auto_run_batches_two_phase.py create_batch_config() must surface subprocess output.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STAGE1 = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "two-phase-handler" / "scripts" / "phase2_stage1.py"
ARP = PROJECT_ROOT / "tasks" / "ut" / "scripts" / "auto_run_batches_two_phase.py"


def _load(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def stage1_mod():
    return _load(STAGE1, "phase2_stage1_reg")


@pytest.fixture(scope="module")
def arp_mod():
    return _load(ARP, "auto_run_batches_two_phase_reg")


class TestF1IgnoredCounted:
    def test_ignored_with_error_type_is_counted(self, stage1_mod):
        # F1: before fix, ignored was skipped -> 0; after fix -> 1
        tests = [{"status": "ignored", "error_type": "timeout", "test_node": "t1", "test_file": "f1"},
                 {"status": "passed", "test_node": "t2", "test_file": "f2"}]
        stats = {}
        stage1_mod.classify(tests, "batch_001", stats)
        assert "timeout" in stats and stats["timeout"]["test_count"] == 1

    def test_passed_still_skipped(self, stage1_mod):
        tests = [{"status": "passed", "error_type": "timeout", "test_node": "t1", "test_file": "f1"}]
        stats = {}
        stage1_mod.classify(tests, "batch_001", stats)
        assert stats == {}


class TestF2NoDoubleCount:
    def test_empty_batch_dir_does_not_pull_all(self, stage1_mod, monkeypatch, tmp_path):
        # F2: an empty batch dir must NOT fall back to all non-pending tests
        run_dir = tmp_path / "run"
        (run_dir / "batches" / "batch_A").mkdir(parents=True)
        (run_dir / "batches" / "batch_B_empty").mkdir(parents=True)  # no test references it
        tl_path = run_dir / "test_load.json"
        tl_path.write_text(json.dumps({"tests": [
            {"status": "failed", "error_type": "timeout", "test_node": "t1",
             "test_file": "f1", "last_batch_id": "batch_A"},
            {"status": "failed", "error_type": "timeout", "test_node": "t2",
             "test_file": "f1", "last_batch_id": "batch_A"}]}), encoding="utf-8")
        (run_dir / "workflow_state.json").write_text(json.dumps(
            {"paths": {"test_load": str(tl_path)}}), encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        monkeypatch.setattr(sys, "argv",
            ["phase2_stage1.py", "--run-dir", str(run_dir), "--output-dir", str(out)])
        stage1_mod.main()
        report = json.loads((out / "phase2_stage1_report.json").read_text(encoding="utf-8"))
        to = report["error_statistics"]["timeout"]
        # before fix: batch_count==2 (double count); after: 1
        assert to["test_count"] == 2
        assert to["batch_count"] == 1
        assert to["batch_list"] == ["batch_A"]


class TestF5SurfaceSubprocessOutput:
    def test_returncode_nonzero_prints_and_raises(self, arp_mod, monkeypatch, tmp_path):
        import io
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, stdout="OUT-FAIL", stderr="ROOT-CAUSE-MSG")
        monkeypatch.setattr(arp_mod.subprocess, "run", fake_run)

        with pytest.raises(subprocess.CalledProcessError):
            arp_mod.create_batch_config("b1", tmp_path / "m.json", tmp_path, 8, tmp_path / "ws.json")
        assert "ROOT-CAUSE-MSG" in buf.getvalue() and "returncode=1" in buf.getvalue()

    def test_exit0_missing_file_prints_and_returns_path(self, arp_mod, monkeypatch, tmp_path):
        import io
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout="OUT", stderr="WARN-PARTIAL")
        monkeypatch.setattr(arp_mod.subprocess, "run", fake_run)

        ret = arp_mod.create_batch_config("b2", tmp_path / "m.json", tmp_path, 8, tmp_path / "ws.json")
        assert "WARN-PARTIAL" in buf.getvalue()
        assert not ret.exists()  # checkpoint 1 will ABORT on this
