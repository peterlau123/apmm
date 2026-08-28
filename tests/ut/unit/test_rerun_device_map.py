"""rerun_selective.py 的 device-map 替换/还原逻辑单测.

2026-08-18 迁移: 原复制实现改为直接调用 rerun_selective 模块函数
(与 test_rerun_selective.py 同源, 保留独立文件以免重复 import 干扰).
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "tasks/ut/scripts/rerun_selective.py"
sys.path.insert(0, str(SCRIPT.parent))
import rerun_selective as rs  # noqa: E402


def test_device_map_run_replace():
    """运行层替换: cuda:1 → cuda:0."""
    dev_map = {"cuda:1": "cuda:0"}
    assert rs.apply_device_map("tests/kernels/core/test_fql.py::test_x[cuda:1-1]", dev_map) \
        == "tests/kernels/core/test_fql.py::test_x[cuda:0-1]"
    assert rs.apply_device_map("tests/lora/test_layers.py::test_y[cuda:1-2]", dev_map) \
        == "tests/lora/test_layers.py::test_y[cuda:0-2]"


def test_device_map_result_restore():
    """回写还原: results 的 cuda:0 → 原 cuda:1."""
    dev_map = {"cuda:1": "cuda:0"}
    assert rs.restore_device_map("tests/kernels/core/test_fql.py::test_x[cuda:0-1]", dev_map) \
        == "tests/kernels/core/test_fql.py::test_x[cuda:1-1]"
    assert rs.restore_device_map("tests/lora/test_layers.py::test_y[cuda:0-2]", dev_map) \
        == "tests/lora/test_layers.py::test_y[cuda:1-2]"


def test_device_map_roundtrip():
    """替换+还原往返 = 原 node."""
    node = "tests/v1/sample/test_sampler.py::test_s[cuda:1-3]"
    dev_map = {"cuda:1": "cuda:0"}
    assert rs.restore_device_map(rs.apply_device_map(node, dev_map), dev_map) == node
