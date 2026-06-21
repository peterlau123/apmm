"""Tests for v5 batch-selector behavior:
- Task 3.1: select_batch with priority sort + retry rules
- Task 3.2: write_batch_config with selected_count + reason

Module is loaded via importlib to match the Phase 1-2 convention.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR_DIR = REPO_ROOT / "skills" / "ut" / "batch-selector" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SELECTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


generate_batch_mod = _load("ut_selector_generate_batch_v5", "generate_batch.py")


def make_test(test_id, status, retry_count=0, max_retry=3):
    return {
        "test_id": test_id,
        "status": status,
        "retry_count": retry_count,
        "max_retry": max_retry,
    }


# --- Task 3.1: select_batch ----------------------------------------------

def test_pending_selected():
    tests = [make_test("t1", "pending")]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert len(selected) == 1
    assert selected[0]["test_id"] == "t1"


def test_error_status_excluded():
    tests = [make_test("t1", "error"), make_test("t2", "pending")]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    ids = [t["test_id"] for t in selected]
    assert "t1" not in ids
    assert "t2" in ids


def test_retriable_error_within_retry_selected():
    tests = [make_test("t1", "retriable_error", retry_count=1, max_retry=3)]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert len(selected) == 1
    assert selected[0]["test_id"] == "t1"


def test_retriable_error_exhausted_excluded():
    tests = [make_test("t1", "retriable_error", retry_count=3, max_retry=3)]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert selected == []


def test_priority_pending_before_failed():
    tests = [
        make_test("f1", "failed", retry_count=0, max_retry=3),
        make_test("p1", "pending"),
    ]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    ids = [t["test_id"] for t in selected]
    assert ids.index("p1") < ids.index("f1")


def test_batch_size_respected():
    tests = [make_test(f"t{i}", "pending") for i in range(20)]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert len(selected) == 8


def test_empty_selectable_returns_empty():
    tests = [make_test("t1", "passed"), make_test("t2", "ignored")]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert selected == []


def test_selected_reason_recorded():
    tests = [make_test("t1", "retriable_error", retry_count=1, max_retry=3)]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    assert "selected_reason" in selected[0]
    assert "retriable_error retry 1/3" in selected[0]["selected_reason"]


# --- Task 3.2: write_batch_config ----------------------------------------

def test_batch_config_json_output(tmp_path):
    tests = [
        make_test("t1", "pending"),
        make_test("t2", "retriable_error", retry_count=1, max_retry=3),
    ]
    selected = generate_batch_mod.select_batch({"tests": tests}, batch_size=8)
    p = tmp_path / "batch_config.json"
    generate_batch_mod.write_batch_config(
        path=p,
        batch_id="b001",
        iteration=42,
        run_id="ut",
        selected=selected,
    )
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert cfg["batch_id"] == "b001"
    assert cfg["iteration"] == 42
    assert cfg["run_id"] == "ut"
    assert cfg["selected_count"] == 2
    assert all("selected_reason" in t for t in cfg["tests"])
