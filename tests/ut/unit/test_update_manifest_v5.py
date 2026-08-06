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


update_test_load_mod = _load("ut_updater_update_test_load_v5", "update_test_load.py")


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
    update_test_load_mod.merge_batch_results(manifest, batch_results, {})
    t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
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
    update_test_load_mod.merge_batch_results(manifest, batch_results, {})
    t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
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
    update_test_load_mod.merge_batch_results(manifest, batch_results, {})
    t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
    assert t1["retry_count"] == 3
    assert t1["status"] == "ignored"
    assert "max retry exceeded for oom" in t1["ignored_reason"]


def test_handled_tests_override_writes_ignored_reason():
    """handled_tests 的 ignored_reason 应写入正确字段（曾写错为 ignore_reason）。"""
    manifest = _make_manifest([
        {"test_id": "t1", "status": "failed", "retry_count": 1, "max_retry": 3},
    ])
    handled = {
        "tests": [{"test_id": "t1", "status": "ignored", "ignored_reason": "manually ignored"}],
    }
    update_test_load_mod.merge_batch_results(manifest, {"batch_id": "b005", "tests": []}, handled)
    t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
    assert t1["status"] == "ignored"
    assert t1["ignored_reason"] == "manually ignored"
    # 错误字段不应再被写入
    assert "ignore_reason" not in t1


def test_handled_tests_legacy_ignore_reason_migrated():
    """旧数据 handled_tests 用 ignore_reason 时，也应迁移写入正确字段 ignored_reason。"""
    manifest = _make_manifest([
        {"test_id": "t1", "status": "failed", "retry_count": 1, "max_retry": 3},
    ])
    handled = {
        "tests": [{"test_id": "t1", "status": "ignored", "ignore_reason": "legacy reason"}],
    }
    update_test_load_mod.merge_batch_results(manifest, {"batch_id": "b006", "tests": []}, handled)
    t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
    assert t1["ignored_reason"] == "legacy reason"
    assert "ignore_reason" not in t1


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
    update_test_load_mod.merge_batch_results(manifest, batch_results, {})
    stats = update_test_load_mod.calculate_statistics(manifest["tests"])
    assert stats.get("passed", 0) == 1
    assert stats.get("retriable_error", 0) == 1
    assert stats.get("failed", 0) == 1
