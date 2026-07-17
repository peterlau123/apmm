"""test_phase2_scripts.py - Test phase2_stage1.py and phase2_stage2.py."""
import json, sys
from pathlib import Path
import pytest
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "two-phase-handler" / "scripts"
@pytest.fixture(scope="module")
def phase2_stage1_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("phase2_stage1", SCRIPTS_DIR / "phase2_stage1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
@pytest.fixture(scope="module")
def phase2_stage2_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("phase2_stage2", SCRIPTS_DIR / "phase2_stage2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
class TestPhase2Stage1:
    def test_classify_groups_by_error_type(self, phase2_stage1_mod):
        tests = [{"status": "failed", "error_type": "timeout", "test_node": "t1", "test_file": "f1"},
                 {"status": "error", "error_type": "oom", "test_node": "t2", "test_file": "f2"},
                 {"status": "failed", "error_type": "timeout", "test_node": "t3", "test_file": "f1"},
                 {"status": "passed", "test_node": "t4", "test_file": "f3"}]
        stats = {}
        phase2_stage1_mod.classify(tests, "batch_001", stats)
        assert "timeout" in stats and stats["timeout"]["test_count"] == 2
        assert "oom" in stats and len(stats) == 2
    def test_classify_tracks_affected_files(self, phase2_stage1_mod):
        tests = [{"status": "failed", "error_type": "timeout", "test_node": "t1", "test_file": "f1"},
                 {"status": "failed", "error_type": "timeout", "test_node": "t2", "test_file": "f1"},
                 {"status": "failed", "error_type": "timeout", "test_node": "t3", "test_file": "f2"}]
        stats = {}
        phase2_stage1_mod.classify(tests, "batch_001", stats)
        assert len(stats["timeout"]["affected_test_files"]) == 2
    def test_classify_missing_error_type_defaults_to_other(self, phase2_stage1_mod):
        tests = [{"status": "failed", "test_node": "t1", "test_file": "f1"}]
        stats = {}
        phase2_stage1_mod.classify(tests, "batch_001", stats)
        assert "other" in stats and stats["other"]["priority"] == "P2"
    def test_gen_md_produces_report(self, phase2_stage1_mod):
        report = {"generated_at": "2026-07-17T00:00:00Z", "meta": {"run_dir": "/tmp", "total_batches": 1},
                  "error_statistics": {"timeout": {"test_count": 1, "batch_count": 1, "batch_list": ["b1"],
                    "affected_test_files": ["f1"], "suggestion": "inc", "priority": "P0"}},
                  "summary": {"total_failed_tests": 1, "error_type_count": 1, "priority_breakdown": {"P0": 1, "P1": 0, "P2": 0}}}
        md = phase2_stage1_mod.gen_md(report)
        assert "# Phase 2 Stage 1" in md and "timeout" in md
class TestPhase2Stage2:
    def test_determine_by_error_type(self, phase2_stage2_mod):
        d = {"decision_method": "retry_error_types", "retry_error_types": ["timeout"]}
        r = {"error_statistics": {"timeout": {"batch_list": ["b1", "b2"]}, "oom": {"batch_list": ["b3"]}}}
        assert set(phase2_stage2_mod.determine_batches(d, r)) == {"b1", "b2"}
    def test_determine_specific(self, phase2_stage2_mod):
        d = {"decision_method": "retry_specific_batches", "retry_specific_batches": ["b5", "b10"]}
        assert set(phase2_stage2_mod.determine_batches(d, {})) == {"b5", "b10"}
    def test_determine_all(self, phase2_stage2_mod):
        d = {"decision_method": "retry_all"}
        r = {"error_statistics": {"timeout": {"batch_list": ["b1"]}, "oom": {"batch_list": ["b2", "b3"]}}}
        assert set(phase2_stage2_mod.determine_batches(d, r)) == {"b1", "b2", "b3"}
    def test_determine_dedup(self, phase2_stage2_mod):
        d = {"decision_method": "retry_all"}
        r = {"error_statistics": {"timeout": {"batch_list": ["b1", "b2"]}, "oom": {"batch_list": ["b2", "b3"]}}}
        assert len(phase2_stage2_mod.determine_batches(d, r)) == 3
