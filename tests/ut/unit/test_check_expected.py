"""Tests for tasks/ut/scripts/check_expected.py — generic run-vs-expected comparator.

Coverage:
  - terminal_state_distribution PASS / FAIL paths (required + expected_offline shapes)
  - anti_fabrication AF-2 (duration sanity) and AF-3 (totals) without remote calls
  - AF-1 SKIP path under --skip-af1
  - stage_invariants STG-1 / STG-2 / STG-3 happy + sad paths
  - dependency_chain_invariants always SKIP (the comparator stubs them)
  - per_test soft-skip path
  - missing manifest -> FAIL with META assertion
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "tasks" / "ut" / "scripts" / "check_expected.py"


@pytest.fixture(scope="module")
def check_mod():
    spec = importlib.util.spec_from_file_location("check_expected", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_expected"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_manifest(run_dir: Path, tests: list[dict], total: int | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "2.0",
        "generated_at": "2026-06-22T00:00:00Z",
        "source": "test_list_file",
        "tests": tests,
        "statistics": {"total": total if total is not None else len(tests)},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


# --- terminal_state_distribution ----------------------------------------


def test_tsd_pass_required_shape(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "last_duration_ms": 50, "run_count": 1},
    ])
    expected = {
        "terminal_state_distribution": {
            "required": {"passed": 1, "failed": 0, "ignored": 0, "pending": 0},
        }
    }
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "PASS"
    assert v.assertions[0].id == "TSD"
    assert v.assertions[0].result == "PASS"


def test_tsd_fail_count_mismatch(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "last_duration_ms": 50, "run_count": 1},
        {"test_node": "t2", "status": "failed", "last_duration_ms": 30, "run_count": 1},
    ])
    expected = {
        "terminal_state_distribution": {
            "required": {"passed": 2, "failed": 0},
        }
    }
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "FAIL"
    fail = next(a for a in v.assertions if a.id == "TSD")
    assert fail.result == "FAIL"


def test_tsd_expected_offline_shape(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [{"test_node": f"t{i}", "status": "ignored",
                               "run_count": 0, "last_duration_ms": None} for i in range(3)])
    expected = {"terminal_state_distribution": {
        "expected_offline": {"passed": 0, "failed": 0, "ignored": 3, "pending": 0},
    }}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "PASS"


# --- anti_fabrication --------------------------------------------------


def test_af1_skip_when_flag_set(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "last_duration_ms": 10, "run_count": 1,
         "log_file": "/remote/fake/path.log"},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    af1 = next(a for a in v.assertions if a.id == "AF-1")
    assert af1.result == "SKIP"
    assert v.overall == "PASS"   # no hard fail


def test_af1_fails_loud_when_log_file_null_on_executed_entry(check_mod, tmp_path, monkeypatch):
    """run_count > 0 with null log_file is itself a FAIL — no remote call needed."""
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "ignored", "run_count": 3,
         "last_duration_ms": 50, "log_file": None},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    # stat must never be invoked when log_file is null
    monkeypatch.setattr(check_mod, "_remote_stat_size",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call stat")))
    v = check_mod.evaluate(run_dir, expected, skip_af1=False, agent_cmd=["nope"])
    af1 = next(a for a in v.assertions if a.id == "AF-1")
    assert af1.result == "FAIL"
    assert any("log_file is null/empty" in x for x in (af1.actual or []))


def test_af1_passes_when_remote_stat_returns_size(check_mod, tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "run_count": 1,
         "last_duration_ms": 50, "log_file": "/remote/log/t1.log"},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    monkeypatch.setattr(check_mod, "_remote_stat_size", lambda *a, **k: 1234)
    v = check_mod.evaluate(run_dir, expected, skip_af1=False, agent_cmd=["nope"])
    af1 = next(a for a in v.assertions if a.id == "AF-1")
    assert af1.result == "PASS"


def test_af1_skips_unrun_entries(check_mod, tmp_path, monkeypatch):
    """run_count == 0 entries (never executed) are exempt — pending/never-run is normal."""
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t_never_run", "status": "ignored", "run_count": 0,
         "last_duration_ms": None, "log_file": None},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    monkeypatch.setattr(check_mod, "_remote_stat_size",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call stat")))
    v = check_mod.evaluate(run_dir, expected, skip_af1=False, agent_cmd=["nope"])
    af1 = next(a for a in v.assertions if a.id == "AF-1")
    assert af1.result == "PASS"


def test_af2_duration_anomaly_fails(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        # passed but duration null -> violation
        {"test_node": "t1", "status": "passed", "last_duration_ms": None, "run_count": 1},
        # ignored with run_count=0 but duration set -> violation
        {"test_node": "t2", "status": "ignored", "last_duration_ms": 999, "run_count": 0},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-2", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    af2 = next(a for a in v.assertions if a.id == "AF-2")
    assert af2.result == "FAIL"
    assert "2 duration anomalies" in af2.detail


def test_af2_pass_with_clean_data(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "last_duration_ms": 10, "run_count": 1},
        {"test_node": "t2", "status": "ignored", "last_duration_ms": None, "run_count": 0},
    ])
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-2", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "PASS"


def test_af3_totals_mismatch_fails(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir,
                    [{"test_node": "t1", "status": "passed",
                      "last_duration_ms": 1, "run_count": 1}],
                    total=3)
    expected = {"anti_fabrication_assertions": [
        {"id": "AF-3", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    af3 = next(a for a in v.assertions if a.id == "AF-3")
    assert af3.result == "FAIL"
    assert "!= total(3)" in af3.detail


# --- stage_invariants --------------------------------------------------


def test_stg1_fail_when_no_retry(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "retry_count": 0,
         "last_duration_ms": 1, "run_count": 1},
    ])
    expected = {"stage_invariants": [
        {"id": "STG-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    stg1 = next(a for a in v.assertions if a.id == "STG-1")
    assert stg1.result == "FAIL"


def test_stg1_pass_when_retry_observed(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "failed", "retry_count": 1,
         "last_duration_ms": 5, "run_count": 2},
    ])
    expected = {"stage_invariants": [
        {"id": "STG-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "PASS"


def test_stg2_over_retry_budget_fails(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "ignored", "retry_count": 5,
         "last_duration_ms": 5, "run_count": 5},
    ])
    expected = {
        "metadata": {"max_retry_per_test": 3},
        "stage_invariants": [
            {"id": "STG-2", "rule": "x", "check": "y", "severity": "hard"},
        ],
    }
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    stg2 = next(a for a in v.assertions if a.id == "STG-2")
    assert stg2.result == "FAIL"


def test_stg3_terminal_retriable_error_fails(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "retriable_error", "retry_count": 3,
         "last_duration_ms": 5, "run_count": 3},
    ])
    expected = {"stage_invariants": [
        {"id": "STG-3", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    stg3 = next(a for a in v.assertions if a.id == "STG-3")
    assert stg3.result == "FAIL"


# --- dependency_chain + per_test (always SKIP) ------------------------


def test_dependency_chain_skipped(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [])
    expected = {"dependency_chain_invariants": [
        {"id": "INV-1", "rule": "x", "check": "y", "severity": "hard"},
    ]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    inv1 = next(a for a in v.assertions if a.id == "INV-1")
    assert inv1.result == "SKIP"
    # all-SKIP run still counts overall as PASS (no hard fail)
    assert v.overall == "PASS"


def test_per_test_emits_soft_skip(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [])
    expected = {"per_test": [{"node": "x"}]}
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    pt = next(a for a in v.assertions if a.id == "PER_TEST")
    assert pt.result == "SKIP"
    assert pt.severity == "soft"


# --- missing manifest ------------------------------------------------


def test_missing_manifest_returns_fail(check_mod, tmp_path):
    run_dir = tmp_path / "empty_run"
    run_dir.mkdir()
    v = check_mod.evaluate(run_dir, {}, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "FAIL"
    assert v.assertions[0].id == "META"


# --- summary line ----------------------------------------------------


def test_summary_counts_hard_assertions(check_mod, tmp_path):
    run_dir = tmp_path / "run"
    _write_manifest(run_dir, [
        {"test_node": "t1", "status": "passed", "last_duration_ms": 5, "run_count": 1},
    ])
    expected = {
        "terminal_state_distribution": {"required": {"passed": 1}},
        "anti_fabrication_assertions": [
            {"id": "AF-2", "rule": "x", "check": "y", "severity": "hard"},
            {"id": "AF-3", "rule": "x", "check": "y", "severity": "hard"},
        ],
    }
    v = check_mod.evaluate(run_dir, expected, skip_af1=True, agent_cmd=["nope"])
    assert v.overall == "PASS"
    # 3 hard pass (TSD, AF-2, AF-3)
    assert "3/3 hard assertions pass" in v.summary
