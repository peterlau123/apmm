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


# --- D1-3 防回归：manifest 冻结 / 不重复选（incident 2026-07-19）----------
# incident 根因：generate_batch 误从冻结的 manifest 选，已跑过的测试在 manifest
# 里仍 pending -> 被反复选中（378 次重复）。方案 A 修复：从 test_load（实时工作集）
# 选，已处理(passed/ignored)的 status 已变 -> select_batch 过滤掉。以下测试锁定该行为。

def _make_full_test(test_id, status, test_file="tests/a.py"):
    """manifest/test_load schema 完整测试项（generate_batch 需 test_node/test_file 等）"""
    return {
        "id": test_id,
        "test_node": f"{test_file}::test_{test_id}",
        "test_file": test_file,
        "test_name": f"test_{test_id}",
        "status": status,
    }


def _write_test_load(tests, tmp_path, name="test_load.json"):
    """写一个符合 manifest schema 的 test_load 文件"""
    data = {
        "version": "2.0",
        "generated_at": "2026-07-19T00:00:00Z",
        "source": "manual",
        "tests": tests,
        "statistics": {
            "total": len(tests),
            "pending": sum(1 for t in tests if t["status"] == "pending"),
        },
    }
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_processed_tests_not_reselected(tmp_path):
    """D1-3: generate_batch 从 test_load 选，已处理(passed)的不被重复选中。

    构造 test_load 含 3 passed + 7 pending。若从冻结 manifest 选会重选 passed；
    从 test_load 选则 passed 被 _is_selectable 过滤，只选 7 个 pending。
    """
    tests = (
        [_make_full_test(i, "passed") for i in range(1, 4)] +      # 3 已跑过
        [_make_full_test(i, "pending") for i in range(4, 11)]      # 7 待跑
    )
    test_load = _write_test_load(tests, tmp_path)
    batch_dir = tmp_path / "batches"

    result = generate_batch_mod.generate_batch(
        manifest_path=test_load,
        batch_dir=batch_dir,
        batch_size=8,
        batch_id="batch_20260719_120000",
    )

    cfg_path = batch_dir / "batch_20260719_120000" / "batch_config.json"
    assert cfg_path.exists(), f"batch_config not written: {result}"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    selected_nodes = [t["test_node"] for t in cfg["tests"]]
    # 只选 7 个 pending，3 个 passed 不应出现
    assert len(selected_nodes) == 7, f"expected 7 pending, got {selected_nodes}"
    for i in range(1, 4):
        assert f"tests/a.py::test_{i}" not in selected_nodes, "passed test re-selected!"
    for i in range(4, 11):
        assert f"tests/a.py::test_{i}" in selected_nodes


def test_ignored_tests_not_reselected(tmp_path):
    """D1-3: ignored（超时/无结果）同样不被重复选中。"""
    tests = (
        [_make_full_test(i, "ignored") for i in range(1, 3)] +     # 2 已超时
        [_make_full_test(i, "pending") for i in range(3, 11)]      # 8 待跑
    )
    test_load = _write_test_load(tests, tmp_path)
    batch_dir = tmp_path / "batches"

    generate_batch_mod.generate_batch(
        manifest_path=test_load,
        batch_dir=batch_dir,
        batch_size=8,
        batch_id="batch_20260719_120001",
    )

    cfg_path = batch_dir / "batch_20260719_120001" / "batch_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    selected_nodes = [t["test_node"] for t in cfg["tests"]]
    assert len(selected_nodes) == 8, f"expected 8 pending, got {selected_nodes}"
    for i in range(1, 3):
        assert f"tests/a.py::test_{i}" not in selected_nodes, "ignored test re-selected!"


def test_no_duplicate_when_reseltilizing_after_partial_run(tmp_path):
    """D1-3: 模拟两轮 generate_batch。首轮选走前 8 pending，第二轮不应重选它们。

    防回归核心：test_load 状态在 execute_batch 后更新（首轮 8 个变 passed），
    第二轮 generate_batch 从更新后的 test_load 选 -> 不重复。这锁定"选择源
    必须是实时 test_load 而非冻结 manifest"。
    """
    tests = [_make_full_test(i, "pending") for i in range(1, 21)]  # 20 pending
    test_load = _write_test_load(tests, tmp_path)
    batch_dir = tmp_path / "batches"

    # 第一轮：选前 8
    generate_batch_mod.generate_batch(
        manifest_path=test_load, batch_dir=batch_dir, batch_size=8,
        batch_id="batch_20260719_120000",
    )
    cfg1 = json.loads((batch_dir / "batch_20260719_120000" / "batch_config.json").read_text(encoding="utf-8"))
    round1_nodes = {t["test_node"] for t in cfg1["tests"]}
    assert len(round1_nodes) == 8

    # 模拟 execute_batch 后 test_load 更新：首轮 8 个变 passed
    for t in tests:
        if t["test_node"] in round1_nodes:
            t["status"] = "passed"
    test_load = _write_test_load(tests, tmp_path)

    # 第二轮：从更新后的 test_load 选，不应重选首轮的 8 个
    generate_batch_mod.generate_batch(
        manifest_path=test_load, batch_dir=batch_dir, batch_size=8,
        batch_id="batch_20260719_120100",
    )
    cfg2 = json.loads((batch_dir / "batch_20260719_120100" / "batch_config.json").read_text(encoding="utf-8"))
    round2_nodes = {t["test_node"] for t in cfg2["tests"]}
    assert len(round2_nodes) == 8
    assert round1_nodes.isdisjoint(round2_nodes), "第二轮重选了首轮已处理的测试！选择源脱节回归"
