#!/usr/bin/env python3
"""Tests for GPU probing and dynamic parallelism in remote_executor.py."""
import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tools.remote_executor import probe_gpus, compute_parallelism


# ── probe_gpus 解析 ──────────────────────────────────────────────────────────

class TestProbeGpus:
    def test_parses_all_idle(self):
        with patch("tools.remote_executor.run_remote", return_value={
            "exit_code": 0, "stdout": (
                "0, 0 %, 0 MiB\n1, 0 %, 0 MiB\n2, 0 %, 0 MiB\n3, 0 %, 0 MiB\n"
            ), "stderr": "", "size_bytes": None,
        }):
            r = probe_gpus(backend="bifrost")
        assert r["total"] == 4
        assert r["idle"] == 4
        assert r["busy"] == 0
        assert all(g["idle"] for g in r["gpus"])

    def test_mixed_busy_idle(self):
        with patch("tools.remote_executor.run_remote", return_value={
            "exit_code": 0, "stdout": (
                "0, 98 %, 81234 MiB\n1, 0 %, 0 MiB\n2, 12 %, 4096 MiB\n3, 1 %, 100 MiB\n"
            ), "stderr": "", "size_bytes": None,
        }):
            r = probe_gpus(backend="bifrost")
        assert r["total"] == 4
        assert r["idle"] == 2  # GPU1 (0%) + GPU3 (1%, 100MiB)
        assert r["busy"] == 2
        assert [g["index"] for g in r["gpus"] if g["idle"]] == [1, 3]

    def test_mem_threshold_borderline(self):
        # util < 5% but mem >= 500MiB -> busy
        with patch("tools.remote_executor.run_remote", return_value={
            "exit_code": 0, "stdout": "0, 0 %, 500 MiB\n1, 0 %, 499 MiB\n",
            "stderr": "", "size_bytes": None,
        }):
            r = probe_gpus(backend="bifrost")
        assert r["idle"] == 1
        assert r["gpus"][0]["idle"] is False  # 500MiB not < 500
        assert r["gpus"][1]["idle"] is True   # 499MiB < 500

    def test_empty_output(self):
        with patch("tools.remote_executor.run_remote", return_value={
            "exit_code": 0, "stdout": "", "stderr": "", "size_bytes": None,
        }):
            r = probe_gpus(backend="bifrost")
        assert r == {"total": 0, "idle": 0, "busy": 0, "gpus": []}

    def test_nonzero_exit_raises(self):
        with patch("tools.remote_executor.run_remote", return_value={
            "exit_code": 1, "stdout": "", "stderr": "nvidia-smi not found", "size_bytes": None,
        }):
            import pytest
            with pytest.raises(ConnectionError):
                probe_gpus(backend="bifrost")


# ── compute_parallelism ──────────────────────────────────────────────────────

class TestComputeParallelism:
    def test_uses_explicit_probe_result(self):
        # 不触发远程调用: 直接传 probe_result
        with patch("tools.remote_executor.probe_gpus") as mock:
            mock.return_value = {"total": 8, "idle": 6, "busy": 2, "gpus": []}
            p = compute_parallelism(probe_result={"idle": 6})
        assert p == 6

    def test_remote_probe_when_no_result(self):
        with patch("tools.remote_executor.probe_gpus", return_value={
            "total": 8, "idle": 3, "busy": 5, "gpus": [],
        }):
            p = compute_parallelism(backend="bifrost")
        assert p == 3

    def test_no_idle_falls_back_to_1(self):
        with patch("tools.remote_executor.probe_gpus", return_value={
            "total": 8, "idle": 0, "busy": 8, "gpus": [],
        }):
            p = compute_parallelism(backend="bifrost")
        assert p == 1

    def test_clamped_to_max_parallel(self):
        with patch("tools.remote_executor.probe_gpus", return_value={
            "total": 8, "idle": 20, "busy": 0, "gpus": [],
        }):
            p = compute_parallelism(max_parallel=10, backend="bifrost")
        assert p == 10

    def test_probe_failure_falls_back_to_max(self):
        with patch("tools.remote_executor.probe_gpus", side_effect=ConnectionError("down")):
            p = compute_parallelism(max_parallel=8, backend="bifrost")
        assert p == 8

    def test_min_parallelism_1(self):
        with patch("tools.remote_executor.probe_gpus", return_value={
            "total": 0, "idle": 0, "busy": 0, "gpus": [],
        }):
            p = compute_parallelism(backend="bifrost")
        assert p == 1
