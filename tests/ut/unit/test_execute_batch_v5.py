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
#
# v6 (2026-06-24-executor-parallel-gpu): the executor now runs each test_node
# in its own docker exec and parses per-node JUnit XML (no grep of pytest
# human output). The batch-level remote_log.raw_log_path still points at
# pytest_<batch_id>.log; per-node log/xml paths land on each test entry.

_PASSING_XML_A = (
    '<?xml version="1.0"?><testsuites><testsuite name="t">'
    '<testcase classname="c" name="test_a" time="0.5">'
    '</testcase></testsuite></testsuites>'
)
_PASSING_XML_B = (
    '<?xml version="1.0"?><testsuites><testsuite name="t">'
    '<testcase classname="c" name="test_b" time="0.7">'
    '</testcase></testsuite></testsuites>'
)


def _decode_inner(cmd: str) -> str:
    import base64 as _b64, re as _re
    m = _re.search(r"echo (\S+) \| base64 -d", cmd)
    return _b64.b64decode(m.group(1)).decode("utf-8") if m else cmd


def test_execute_batch_writes_remote_log_pointer_and_local_summary(tmp_path):
    """The executor produces:
    - batch_results.json with remote_log.raw_log_path naming pytest_<batch_id>.log
    - per-test entries with status parsed from JUnit XML
    - a local summary.txt next to batch_results.json
    """
    cfg = _write_batch_config(tmp_path)
    state = _write_workflow_state(tmp_path)

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        inner = _decode_inner(cmd)
        # The XML-fetch call `cat <node_xml>` returns the parsed XML; the
        # watchdog exec returns empty stdout.
        if "cat " in inner:
            xml = _PASSING_XML_B if "test_b" in inner else _PASSING_XML_A
            return {"exit_code": 0, "stdout": xml, "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 4242}

    with mock.patch.object(execute_batch_mod, "run_remote",
                           side_effect=fake_run_remote), \
         mock.patch.object(execute_batch_mod, "_detect_free_gpus",
                           return_value=([0, 1], 0)):
        result = execute_batch_mod.execute_batch(cfg, state)

    out = json.loads((tmp_path / "batch_results.json").read_text(encoding="utf-8"))

    assert "remote_log" in out
    rlog = out["remote_log"]
    # Batch-level pointer filename is pytest_<batch_id>.log
    assert rlog["raw_log_path"].endswith("/pytest_batch_p1_r1_w1_test.log")
    assert "host" in rlog and "container" in rlog
    assert rlog["captured_at"].endswith("Z")

    summary_path = tmp_path / "summary.txt"
    assert summary_path.exists()
    summary = summary_path.read_text(encoding="utf-8")
    # Aggregated per-test outcomes mention each node.
    assert "tests/test_x.py::test_a" in summary
    assert "tests/test_x.py::test_b" in summary

    # Per-test entries parsed from JUnit: passed + real duration_ms.
    assert len(out["tests"]) == 2
    for t in out["tests"]:
        assert t["status"] == "passed"
        assert t["error_type"] is None
        assert t["duration_ms"] in (500, 700)
        assert t["gpu_id"] in (0, 1)



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
#
# RETIRED in v6 (2026-06-24-executor-parallel-gpu): Bug #2 was that pytest
# abbreviates long parametrized node ids in human-readable `-v` output, so
# grep-based per-test classification mis-matched. The v6 executor runs each
# node in its own docker exec with --junit-xml, so pytest itself is the source
# of truth — there is no human-output grep to abbreviate. The old
# `_classify_for_test` helper was removed; JUnit parsing (test_execute_batch_junit.py)
# covers the status mapping. Bug #2 is structurally impossible in v6.
