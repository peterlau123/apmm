"""rerun_selective.py 单测: 过滤/分组/device-map/batch_config/解析/回写/执行流程.

2026-08-18 随 rerun_selective.py (5 脚本整合) 新增; 迁移自 test_rerun_device_map.py.
"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPT = Path(__file__).parents[3] / "tasks/ut/scripts/rerun_selective.py"

sys.path.insert(0, str(SCRIPT.parent))
import rerun_selective as rs  # noqa: E402


# ---------- 过滤 ----------

def _t(node, status="ignored", err="", f="", retry=0):
    return {"test_node": node, "status": status, "error_message": err,
            "test_file": f, "retry_count": retry}


def test_classify_categories():
    """_classify 覆盖兼容性 SKIP 六类 + 可重跑组."""
    assert rs._classify(_t("x", err="NotImplementedError")) == "_C算子"
    assert rs._classify(_t("x", f="test_fp8_kernel.py")) == "FP8"
    assert rs._classify(_t("x", f="test_inductor_fusion.py")) == "inductor"
    assert rs._classify(_t("x", f="test_flash_attn_mla.py")) == "flash/mla"
    assert rs._classify(_t("x", f="test_cutlass_machete.py")) == "cutlass"
    assert rs._classify(_t("x", err="module 'torch' has no attribute 'x'")) == "torch API"
    assert rs._classify(_t("x", err="watchdog SIGKILL")) == "timeout"
    assert rs._classify(_t("x", err="LocalEntryNotFound")) == "models"
    assert rs._classify(_t("x", err="SKIPPED")) == "skipped"
    assert rs._classify(_t("x", err="assert x == y")) == "other"


def test_select_by_status():
    tests = [_t("a", "ignored"), _t("b", "failed"), _t("c", "ignored")]
    got = rs.select_targets(tests, status="failed")
    assert [t["test_node"] for t in got] == ["b"]


def test_select_category_all_excludes_skip_categories():
    """category=all 排除兼容性 SKIP 类 (用户拍板不重跑)."""
    tests = [_t("a", "ignored", err="NotImplementedError"),   # _C算子
             _t("b", "ignored", f="test_fp8.py"),             # FP8
             _t("c", "ignored", err="assert 1==2"),           # other → 保留
             _t("d", "ignored", err="LocalEntryNotFound")]    # models → 保留
    got = rs.select_targets(tests, status="ignored", category="all")
    assert [t["test_node"] for t in got] == ["c", "d"]


def test_select_category_specific():
    tests = [_t("a", "ignored", err="NotImplementedError"),
             _t("b", "ignored", err="assert 1==2")]
    got = rs.select_targets(tests, status="ignored", category="_C算子")
    assert [t["test_node"] for t in got] == ["a"]


def test_select_match_node_and_error():
    tests = [_t("tests/a.py::x", "ignored", err="ProcessRaisedException"),
             _t("tests/b.py::y", "ignored", err="ProcessRaisedException"),
             _t("tests/c.py::z", "ignored", err="assert")]
    got = rs.select_targets(tests, status="ignored",
                            match_node=("a.py",), match_error=("ProcessRaisedException",))
    assert [t["test_node"] for t in got] == ["tests/a.py::x"]
    # 多个 match 需全含
    got2 = rs.select_targets(tests, status="ignored",
                             match_node=("tests/", "b.py"), match_error=("ProcessRaisedException",))
    assert [t["test_node"] for t in got2] == ["tests/b.py::y"]


def test_select_limit():
    tests = [_t(f"n{i}", "ignored") for i in range(10)]
    assert len(rs.select_targets(tests, status="ignored", limit=3)) == 3


def test_select_skip_files_and_no_skip():
    tests = [_t("tests/test_detokenize.py::x", "ignored"),
             _t("tests/test_peft_helper.py::y", "ignored"),
             _t("tests/test_sampler.py::z", "ignored")]
    assert len(rs.select_targets(tests, status="ignored")) == 1
    assert len(rs.select_targets(tests, status="ignored", no_skip=True)) == 3


def test_select_only_retry_zero():
    tests = [_t("a", "ignored", retry=0), _t("b", "ignored", retry=2)]
    got = rs.select_targets(tests, status="ignored", only_retry_zero=True)
    assert [t["test_node"] for t in got] == ["a"]


# ---------- 分组 / device-map / batch_config ----------

def test_make_groups():
    groups = rs.make_groups(list(range(17)), 8)
    assert [len(g) for g in groups] == [8, 8, 1]


def test_device_map_apply_restore_roundtrip():
    dev_map = {"cuda:1": "cuda:0"}
    node = "tests/v1/sample/test_sampler.py::test_s[cuda:1-3]"
    run_node = rs.apply_device_map(node, dev_map)
    assert run_node == "tests/v1/sample/test_sampler.py::test_s[cuda:0-3]"
    assert rs.restore_device_map(run_node, dev_map) == node


def test_build_batch_config_shape():
    t = _t("tests/a.py::x", "ignored")
    cfg = rs.build_batch_config("batch_ig_0001", [t], generated_at="2026-08-18T00:00:00")
    assert cfg["batch_id"] == "batch_ig_0001"
    assert cfg["tests"] == [t]
    assert cfg["gpu_per_test"] == 1


# ---------- pytest 输出解析 (ssh 模式) ----------

def test_parse_pytest_passed():
    r = rs.parse_pytest_output("1 passed, 3 warnings in 2.19s", 3.0)
    assert r["status"] == "passed" and r["duration_ms"] == 2190


def test_parse_pytest_failed():
    r = rs.parse_pytest_output("1 failed, 1 error in 2.40s\nE assert 1==2", 3.0)
    assert r["status"] == "error"  # error 优先于 failed
    assert "assert 1==2" in r["error_message"]


def test_parse_pytest_skipped():
    r = rs.parse_pytest_output("2 skipped in 1.0s", 2.0)
    assert r["status"] == "ignored" and r["error_type"] == "filtered"


def test_parse_pytest_not_found():
    r = rs.parse_pytest_output("ERROR: not found: tests/kernels/core/test_x.py", 1.0)
    assert r["status"] == "ignored" and r["error_type"] == "timeout"


def test_parse_pytest_unparsed():
    r = rs.parse_pytest_output("INTERNALERROR: weird", 1.0)
    assert r["status"] == "ignored" and r["error_type"] == "other"


# ---------- 回写 (ssh 模式直写) ----------

def test_write_back_direct(tmp_path):
    tl = {"tests": [
        {"test_node": "a", "status": "ignored", "run_count": 0},
        {"test_node": "b", "status": "ignored", "run_count": 0},
    ]}
    (tmp_path / "test_load_1.json").write_text(json.dumps(tl))
    results = {"a": {"status": "passed", "error_type": None, "error_message": "",
                     "duration_ms": 100}}
    rs.write_back_direct(tmp_path, results)
    tl2 = json.loads((tmp_path / "test_load_1.json").read_text())
    by_node = {t["test_node"]: t for t in tl2["tests"]}
    assert by_node["a"]["status"] == "passed"
    assert by_node["a"]["run_count"] == 1
    assert by_node["b"]["status"] == "ignored"  # 未跑的不动


# ---------- batch 模式执行流程 (mock subprocess) ----------

def _fake_batch_results(statistics):
    return {"statistics": statistics, "tests": []}


def test_batch_mode_end_to_end(tmp_path):
    """mock subprocess.run: 验证 写 config → execute_batch → 回写 → 汇总."""
    tl = {"tests": [_t("tests/a.py::x", "ignored", err="assert"),
                    _t("tests/b.py::y", "ignored", err="assert"),
                    _t("tests/c.py::z", "ignored", err="assert")]}
    (tmp_path / "test_load_1.json").write_text(json.dumps(tl))
    (tmp_path / "workflow_state.json").write_text(json.dumps({"paths": {}}))

    calls = []
    def fake_run(cmd, capture_output=True, text=True, env=None, timeout=None):
        calls.append(cmd)
        is_exec = "--batch-config" in cmd  # update 回写调用不写 brp
        if is_exec:
            for i, c in enumerate(cmd):
                if c == "--batch-id":
                    bid = cmd[i + 1]
                    brp = tmp_path / "batches" / bid / "batch_results.json"
                    brp.write_text(json.dumps(_fake_batch_results(
                        {"passed": 2, "failed": 0, "ignored": 0})))
        return mock.Mock(returncode=0, stdout="", stderr="")

    env = rs.build_env("/tmp/bifrost.json", "/tmp/hf")
    with mock.patch("rerun_selective.subprocess.run", side_effect=fake_run):
        rs.run_batch_mode(tmp_path, rs.select_targets(tl["tests"], status="ignored"),
                          prefix="ig", batch_size=2, batch_timeout=900,
                          device_map={}, env=env)

    # 2 组 → 2 个 batch_config + 2 次 execute_batch + 2 次回写
    batch_cfgs = [c for c in calls if "--batch-config" in c]
    upd_calls = [c for c in calls if any("update_test_load_two_phase" in str(x) for x in c)]
    assert len(batch_cfgs) == 2
    assert len(upd_calls) == 2
    cfg0 = json.loads((tmp_path / "batches" / "batch_ig_0001" / "batch_config.json").read_text())
    assert len(cfg0["tests"]) == 2
    cfg1 = json.loads((tmp_path / "batches" / "batch_ig_0002" / "batch_config.json").read_text())
    assert len(cfg1["tests"]) == 1


def test_batch_mode_resume_skips_done(tmp_path):
    """断点续跑: 已有 batch_results.json 的 batch 跳过."""
    tl = {"tests": [_t("a", "ignored", err="assert"), _t("b", "ignored", err="assert")]}
    (tmp_path / "test_load_1.json").write_text(json.dumps(tl))
    (tmp_path / "workflow_state.json").write_text(json.dumps({}))
    done_dir = tmp_path / "batches" / "batch_ig_0001"
    done_dir.mkdir(parents=True)
    (done_dir / "batch_results.json").write_text(json.dumps({"statistics": {}}))

    calls = []
    def fake_run(cmd, capture_output=True, text=True, env=None, timeout=None):
        calls.append(cmd)
        is_exec = "--batch-config" in cmd
        if is_exec:
            for i, c in enumerate(cmd):
                if c == "--batch-id":
                    bid = cmd[i + 1]
                    brp = tmp_path / "batches" / bid / "batch_results.json"
                    brp.write_text(json.dumps(_fake_batch_results(
                        {"passed": 1, "failed": 0, "ignored": 0})))
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("rerun_selective.subprocess.run", side_effect=fake_run):
        rs.run_batch_mode(tmp_path, rs.select_targets(tl["tests"], status="ignored"),
                          prefix="ig", batch_size=1, batch_timeout=900,
                          device_map={}, env={})
    exec_calls = [c for c in calls if "--batch-config" in c]
    assert len(exec_calls) == 1  # 0001 跳过, 只跑 batch_ig_0002


def test_batch_mode_device_map_roundtrip(tmp_path):
    """batch 模式: 运行层替换 cuda:1→cuda:0, 回写前还原."""
    tl = {"tests": [_t("tests/x.py::t[cuda:1-1]", "ignored", err="assert")]}
    (tmp_path / "test_load_1.json").write_text(json.dumps(tl))
    (tmp_path / "workflow_state.json").write_text(json.dumps({}))

    cfg_seen = {}
    def fake_run(cmd, capture_output=True, text=True, env=None, timeout=None):
        is_exec = "--batch-config" in cmd
        if is_exec:
            for i, c in enumerate(cmd):
                if c == "--batch-config":
                    cfg = json.loads(Path(cmd[i + 1]).read_text())
                    cfg_seen["run_node"] = cfg["tests"][0]["test_node"]
                if c == "--batch-id":
                    brp = tmp_path / "batches" / cmd[i + 1] / "batch_results.json"
                    brp.parent.mkdir(parents=True, exist_ok=True)
                    brp.write_text(json.dumps({
                        "statistics": {"passed": 1},
                        "tests": [{"test_node": "tests/x.py::t[cuda:0-1]", "status": "passed"}],
                    }))
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("rerun_selective.subprocess.run", side_effect=fake_run):
        rs.run_batch_mode(tmp_path, rs.select_targets(tl["tests"], status="ignored"),
                          prefix="ig", batch_size=8, batch_timeout=900,
                          device_map={"cuda:1": "cuda:0"}, env={})
    assert cfg_seen["run_node"] == "tests/x.py::t[cuda:0-1]"  # 运行层已替换
    # 回写前的 batch_results 已还原为原 node
    brp = tmp_path / "batches" / "batch_ig_0001" / "batch_results.json"
    br = json.loads(brp.read_text())
    assert br["tests"][0]["test_node"] == "tests/x.py::t[cuda:1-1]"


# ---------- ssh 模式执行流程 (mock subprocess) ----------

def test_ssh_mode_progress_and_write_back(tmp_path):
    """ssh 模式: 断点续跑跳过已有 progress + 直写回写."""
    tl = {"tests": [_t("tests/k/a.py::x", "ignored"),
                    _t("tests/k/b.py::y", "ignored"),
                    _t("tests/k/c.py::z", "ignored")]}
    (tmp_path / "test_load_1.json").write_text(json.dumps(tl))
    # 已有 progress: a 已跑过 → 应跳过
    (tmp_path / "retry_kernel_progress.json").write_text(json.dumps(
        {"tests/k/a.py::x": {"status": "passed", "duration_ms": 100}}))

    def fake_ssh_one(host, container, vllm_dir, node, timeout=180):
        return {"status": "passed", "error_type": None, "error_message": "",
                "duration_ms": 100}

    with mock.patch("rerun_selective.run_ssh_one", side_effect=fake_ssh_one):
        rs.run_ssh_mode(tmp_path, rs.select_targets(tl["tests"], status="ignored"),
                        host="h", container="c", vllm_dir="v", tag="kernel",
                        device_map={}, ssh_timeout=180)
    tl2 = json.loads((tmp_path / "test_load_1.json").read_text())
    by_node = {t["test_node"]: t for t in tl2["tests"]}
    assert by_node["tests/k/a.py::x"]["status"] == "passed"
    assert by_node["tests/k/b.py::y"]["status"] == "passed"
    assert by_node["tests/k/c.py::z"]["status"] == "passed"
    prog = json.loads((tmp_path / "retry_kernel_progress.json").read_text())
    assert len(prog) == 3  # a 保留 + b/c 新增


def test_load_test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        rs.load_test_load(tmp_path)
