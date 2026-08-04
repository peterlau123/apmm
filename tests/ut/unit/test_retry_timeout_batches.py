"""retry_timeout_batches.py 慢测试剔除逻辑测试 (2026-08-04)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tasks.ut.scripts.retry_timeout_batches import (  # noqa: E402
    is_slow_test,
    load_slow_tests,
)


@pytest.fixture
def run_dir(tmp_path):
    tl = {
        "tests": [
            {"test_id": 1, "test_node": "tests/x.py::test_a", "status": "ignored",
             "retry_count": 5, "ignored_reason": "max retry exceeded for other"},
            {"test_id": 2, "test_node": "tests/x.py::test_b", "status": "ignored",
             "retry_count": 2, "error_type": "timeout"},
            {"test_id": 3, "test_node": "tests/x.py::test_c", "status": "passed",
             "retry_count": 3},
            {"test_id": 4, "test_node": "tests/x.py::test_d", "status": "ignored",
             "retry_count": 0, "error_type": "timeout"},
        ]
    }
    (tmp_path / "test_load_4000_x.json").write_text(json.dumps(tl))
    return tmp_path


def test_load_slow_tests_only_ignored_retry3plus(run_dir):
    """只收集 status=ignored 且 retry_count>=3 的测试 (test_id 数字 + test_node)."""
    slow, xml_prefixes = load_slow_tests(run_dir)
    assert set(slow) == {"1", "tests/x.py::test_a"}
    assert slow["1"] == "max retry exceeded for other"
    assert xml_prefixes == []


def test_load_slow_tests_writes_manifest(run_dir):
    """清单落盘 retry_slow_tests.json 供后续单独处理."""
    load_slow_tests(run_dir)
    out = json.loads((run_dir / "retry_slow_tests.json").read_text())
    assert "1" in out["slow"]
    assert "xml_prefixes" in out


def test_load_slow_tests_no_test_load(tmp_path):
    """无 test_load 文件时不崩, 返回空集合."""
    slow, xml_prefixes = load_slow_tests(tmp_path)
    assert slow == {}
    assert xml_prefixes == []


def test_load_slow_tests_xml_scan(tmp_path):
    """XML 实测 >threshold 的测试生成 test_node 前缀."""
    (tmp_path / "test_load_4000_x.json").write_text(json.dumps({"tests": []}))
    bdir = tmp_path / "batch_0001"
    bdir.mkdir()
    xml = ('<testsuite><testcase classname="tests.compile.distributed.'
           'test_sequence_parallelism" name="test_sequence_parallelism_pass'
           '[False-True-dtype0-16-16-8]"/>'
           '<testcase classname="tests.kernels.test_fast" '
           'name="test_fast[0]" time="2.0"/></testsuite>')
    (bdir / "result_batch_0001_a.xml").write_text(xml)
    # 注意: 无 time 属性默认 0, 不会触发; 构造带 time 的慢测试
    (bdir / "result_batch_0001_b.xml").write_text(
        '<testsuite><testcase classname="tests.compile.distributed.'
        'test_sequence_parallelism" name="test_sequence_parallelism_pass'
        '[True-True-dtype1-16-16-8]" time="1210.5"/></testsuite>')
    slow, xml_prefixes = load_slow_tests(tmp_path, ut_logs_base=tmp_path)
    assert ("tests/compile/distributed/test_sequence_parallelism.py::"
            "test_sequence_parallelism_pass") in xml_prefixes


def test_is_slow_test_matches_three_ways(run_dir):
    """is_slow_test 覆盖 test_id / test_node / XML 前缀三种匹配."""
    slow, xml_prefixes = load_slow_tests(run_dir)
    # test_id 数字匹配
    assert is_slow_test({"id": 1, "test_node": "tests/x.py::test_a"}, slow, xml_prefixes)
    # test_node 精确匹配
    assert is_slow_test({"id": 99, "test_node": "tests/x.py::test_a"}, slow, xml_prefixes)
    # 正常测试不匹配
    assert not is_slow_test({"id": 2, "test_node": "tests/x.py::test_b"}, slow, xml_prefixes)
    # XML 前缀匹配
    xml_prefixes.append("tests/slow.py::test_slow")
    assert is_slow_test({"id": 7, "test_node": "tests/slow.py::test_slow[x-1]"}, slow, xml_prefixes)
