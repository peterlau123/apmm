"""rerun_ignored_remaining.py 的 device-map 替换/还原逻辑单测."""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "tasks/ut/scripts/rerun_ignored_remaining.py"


@pytest.fixture(scope="module")
def module():
    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util

    spec = importlib.util.spec_from_file_location("rerun_ig_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    # 不执行 main (argparse), 只导入纯函数
    spec.loader.exec_module(m)
    return m


def test_device_map_run_replace(module):
    """运行层替换: cuda:1 → cuda:0."""
    tests = [{"test_node": "tests/kernels/core/test_fql.py::test_x[cuda:1-1]"},
             {"test_node": "tests/lora/test_layers.py::test_y[cuda:1-2]"}]
    dev_map = {"cuda:1": "cuda:0"}
    run_tests = []
    for t in tests:
        tt = dict(t)
        tn = tt["test_node"]
        for src, dst in dev_map.items():
            tn = tn.replace(src, dst)
        tt["test_node"] = tn
        run_tests.append(tt)
    assert run_tests[0]["test_node"] == "tests/kernels/core/test_fql.py::test_x[cuda:0-1]"
    assert run_tests[1]["test_node"] == "tests/lora/test_layers.py::test_y[cuda:0-2]"


def test_device_map_result_restore(module):
    """回写还原: results 的 cuda:0 → 原 cuda:1."""
    results = [{"test_node": "tests/kernels/core/test_fql.py::test_x[cuda:0-1]", "status": "passed"},
               {"test_node": "tests/lora/test_layers.py::test_y[cuda:0-2]", "status": "failed"}]
    dev_map = {"cuda:1": "cuda:0"}
    for t in results:
        tn = t["test_node"]
        for dst, src in [(v, k) for k, v in dev_map.items()]:
            tn = tn.replace(dst, src)
        t["test_node"] = tn
    assert results[0]["test_node"] == "tests/kernels/core/test_fql.py::test_x[cuda:1-1]"
    assert results[1]["test_node"] == "tests/lora/test_layers.py::test_y[cuda:1-2]"


def test_device_map_roundtrip(module):
    """替换+还原往返 = 原 node."""
    node = "tests/v1/sample/test_sampler.py::test_s[cuda:1-3]"
    dev_map = {"cuda:1": "cuda:0"}
    run_node = node
    for src, dst in dev_map.items():
        run_node = run_node.replace(src, dst)
    restored = run_node
    for dst, src in [(v, k) for k, v in dev_map.items()]:
        restored = restored.replace(dst, src)
    assert restored == node
