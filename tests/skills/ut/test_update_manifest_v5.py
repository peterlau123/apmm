"""Tests for v5 manifest-updater behavior:
- Task 4.1: update_manifest merge logic (last_batch_id, retry_count, retriable_error->ignored, stats)
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATER_DIR = REPO_ROOT / "skills" / "ut" / "manifest-updater" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, UPDATER_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


update_manifest_mod = _load("ut_updater_update_manifest_v5", "update_manifest.py")


def _make_manifest(tests):
    return {"tests": tests, "statistics": {}}


def test_last_batch_id_set_after_merge():
    manifest = _make_manifest([
        {"test_id": "t1", "status": "pending", "retry_count": 0, "max_retry": 3},
    ])
    batch_results = {
        "batch_id": "b001",
        "tests": [{"test_id": "t1", "status": "passed"}],
    }
    out = update_manifest_mod.update_manifest(manifest, batch_results, {})
    t1 = next(t for t in out["tests"] if t["test_id"] == "t1")
    assert t1["last_batch_id"] == "b001"
    assert t1["status"] == "passed"


def test_retry_count_incremented_on_failure():
    manifest = _make_manifest([
        {"test_id": "t1", "status": "pending", "retry_count": 0, "max_retry": 3},
    ])
    batch_results = {
        "batch_id": "b002",
        "tests": [{"test_id": "t1", "status": "failed", "error_type": "assertion"}],
    }
    out = update_manifest_mod.update_manifest(manifest, batch_results, {})
    t1 = next(t for t in out["tests"] if t["test_id"] == "t1")
    assert t1["retry_count"] == 1
    assert t1["status"] == "failed"
    assert t1["error_type"] == "assertion"


def test_retriable_error_max_retry_becomes_ignored():
    manifest = _make_manifest([
        {"test_id": "t1", "status": "retriable_error", "retry_count": 2, "max_retry": 3},
    ])
    batch_results = {
        "batch_id": "b003",
        "tests": [{"test_id": "t1", "status": "retriable_error", "error_type": "oom"}],
    }
    out = update_manifest_mod.update_manifest(manifest, batch_results, {})
    t1 = next(t for t in out["tests"] if t["test_id"] == "t1")
    assert t1["retry_count"] == 3
    assert t1["status"] == "ignored"
    assert "max retry exceeded for oom" in t1["ignore_reason"]


def test_statistics_includes_retriable_error_count():
    manifest = _make_manifest([
        {"test_id": "t1", "status": "pending", "retry_count": 0, "max_retry": 3},
        {"test_id": "t2", "status": "pending", "retry_count": 0, "max_retry": 3},
        {"test_id": "t3", "status": "pending", "retry_count": 0, "max_retry": 3},
    ])
    batch_results = {
        "batch_id": "b004",
        "tests": [
            {"test_id": "t1", "status": "passed"},
            {"test_id": "t2", "status": "retriable_error", "error_type": "timeout"},
            {"test_id": "t3", "status": "failed", "error_type": "assertion"},
        ],
    }
    out = update_manifest_mod.update_manifest(manifest, batch_results, {})
    stats = out["statistics"]
    assert stats.get("passed", 0) == 1
    assert stats.get("retriable_error", 0) == 1
    assert stats.get("failed", 0) == 1
