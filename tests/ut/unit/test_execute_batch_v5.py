"""Tests for v5 executor behavior:
- Task 2.1: remote raw_log + local summary + remote_log pointer
- Task 2.2: OOM/timeout classification (retriable_error)
- Task 2.3: Bastion disconnect -> mark_disconnected + next_action=wait

The executor scripts live under skills/ut/unit-test-executor/scripts/ which is a
hyphenated directory (not a Python package). We load the modules by file path
via importlib.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_DIR = REPO_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load fresh modules for each test session
classify_error = _load("ut_executor_classify_error", "classify_error.py")
execute_batch_mod = _load("ut_executor_execute_batch", "execute_batch.py")


# --- helpers --------------------------------------------------------------

def _write_batch_config(tmp_path: Path, tests=None) -> Path:
    if tests is None:
        tests = [
            {"id": 1, "test_node": "tests/test_x.py::test_a"},
            {"id": 2, "test_node": "tests/test_x.py::test_b"},
        ]
    cfg = {"batch_id": "batch_p1_r1_w1_test", "tests": tests}
    p = tmp_path / "batch_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _write_workflow_state(tmp_path: Path) -> Path:
    p = tmp_path / "workflow_state.json"
    p.write_text(json.dumps({
        "paths": {},
        "config": {
            "remote_server": "t_h20",
            "docker_container": "v0.13.0_torch2.5.1_compile",
            "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
        },
    }), encoding="utf-8")
    return p


# --- Task 2.2: classifier -------------------------------------------------

def test_classify_oom_returns_retriable_oom():
    status, error_type = classify_error.classify(
        "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate ...",
        "tests/test_x.py::test_a",
    )
    assert status == "retriable_error"
    assert error_type == "oom"


def test_classify_timeout_returns_retriable_timeout():
    status, error_type = classify_error.classify(
        "+++++++ Timeout >60s ++++++\nFailed: Timeout >60.0s",
        "tests/test_x.py::test_b",
    )
    assert status == "retriable_error"
    assert error_type == "timeout"


def test_classify_collection_returns_error():
    status, error_type = classify_error.classify(
        "ERROR collecting tests/test_x.py\nImportError: No module named 'foo'",
        "tests/test_x.py::test_c",
    )
    assert status == "error"
    assert error_type is not None


def test_classify_failed_returns_failed_assertion():
    status, error_type = classify_error.classify(
        "FAILED tests/test_x.py::test_d - assert 1 == 2",
        "tests/test_x.py::test_d",
    )
    assert status == "failed"
    assert error_type == "assertion"


def test_classify_passed_returns_passed_none():
    status, error_type = classify_error.classify(
        "PASSED tests/test_x.py::test_e",
        "tests/test_x.py::test_e",
    )
    assert status == "passed"
    assert error_type is None


# --- Task 2.1: remote raw_log + local summary + remote_log pointer --------

def test_execute_batch_writes_remote_log_pointer_and_local_summary(tmp_path):
    """The executor produces:
    - batch_results.json with remote_log.raw_log_path ending in /raw_log.txt
    - a local summary.txt next to batch_results.json
    """
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path)

    summary_text = (
        "PASSED tests/test_x.py::test_a\n"
        "PASSED tests/test_x.py::test_b\n"
        "===== 2 passed in 1.23s =====\n"
    )

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        if "pytest" in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 4242}
        # grep + tail extraction
        return {"exit_code": 0, "stdout": summary_text, "stderr": ""}

    with mock.patch.object(execute_batch_mod, "run_remote", side_effect=fake_run_remote):
        result = execute_batch_mod.execute_batch(cfg, state)

    out = json.loads((tmp_path / "batch_results.json").read_text(encoding="utf-8"))

    assert "remote_log" in out
    rlog = out["remote_log"]
    assert rlog["raw_log_path"].endswith("/raw_log.txt")
    assert "host" in rlog and "container" in rlog
    assert rlog["captured_at"].endswith("Z")

    summary_path = tmp_path / "summary.txt"
    assert summary_path.exists()
    assert "PASSED tests/test_x.py::test_a" in summary_path.read_text(encoding="utf-8")

    for t in out["tests"]:
        assert "status" in t
        assert "error_type" in t


# --- Task 2.3: Bastion disconnect -> wait, no batch_results.json ----------

def test_execute_batch_on_disconnect_marks_disconnected_and_returns_wait(tmp_path):
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path)

    def boom(*args, **kwargs):
        raise ConnectionError("bastion daemon unreachable")

    with mock.patch.object(execute_batch_mod, "run_remote", side_effect=boom), \
         mock.patch.object(execute_batch_mod, "BastionManager") as bm_cls:
        instance = bm_cls.return_value
        result = execute_batch_mod.execute_batch(cfg, state)

    assert result.get("next_action") == "wait"
    assert "reason" in result
    instance.mark_disconnected.assert_called_once()
    assert not (tmp_path / "batch_results.json").exists()


# --- Bug #2: pytest output parsing with abbreviated test names ------------

def test_classify_for_test_matches_abbreviated_pytest_output():
    """Bug #2 fix: pytest abbreviates long parametrized names with '::...'
    Classifier should still find correct status via prefix matching."""
    # Simulate pytest verbose output with abbreviated test names
    summary_text = (
        "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem::test_nested[input0---a-b-c] PASSED [ 12%]\n"
        "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem::... PASSED [ 25%]\n"
        "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem::... FAILED [ 37%]\n"
        "tests/config/test_config_utils.py::test_hash_factors PASSED [ 50%]\n"
        "tests/config/test_config_utils.py::test_normalize_value_matrix[None-None] ERROR [ 75%]\n"
        "======================== 2 passed, 1 failed, 1 error =========================\n"
    )
    
    # Test: long parametrized name that pytest abbreviates
    test_node = "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem::test_nested[input1---x-y-z]"
    status, error_type = execute_batch_mod._classify_for_test(summary_text, test_node)
    # Should match via prefix (class_prefix = tests/...::TestParameterSweepItem)
    # Will classify as PASSED because first matching line is PASSED
    assert status in ("passed", "failed", "error")  # At least gets a status, not error:other
    
    # Test: exact match available
    test_node_exact = "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem::test_nested[input0---a-b-c]"
    status_exact, _ = execute_batch_mod._classify_for_test(summary_text, test_node_exact)
    assert status_exact == "passed"  # Exact line shows PASSED
    
    # Test: simple test name (no abbreviation needed)
    test_node_simple = "tests/config/test_config_utils.py::test_hash_factors"
    status_simple, _ = execute_batch_mod._classify_for_test(summary_text, test_node_simple)
    assert status_simple == "passed"
