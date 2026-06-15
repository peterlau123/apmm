#!/usr/bin/env python3
"""gpu_scheduler.py - GPU分配调度器

职责：
- 检测可用 GPU 数量（从远程 nvidia-smi 获取）
- 分配 test_file 到 GPU slot（round-robin）
- 管理 CUDA_VISIBLE_DEVICES 设置
- 输出 GPU 分配日志（batch_logs_dir/gpu_scheduler.log）

Usage:
    from gpu_scheduler import GPUScheduler
    scheduler = GPUScheduler(config)
    assignments = scheduler.assign_to_gpus(file_groups)
"""

import json
import os
import subprocess
import logging
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GPUScheduler:
    """GPU资源调度器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.remote_server = config.get("remote_server", "t_h20")
        self.max_gpus = config.get("max_gpus", 8)
        self.log_path = None

    def detect_available_gpus(self) -> List[int]:
        """检测可用 GPU ID 列表（从远程 nvidia-smi 获取）"""
        cmd = "nvidia-smi --query-gpu=index --format=csv,noheader,nounits"
        try:
            result = subprocess.run(
                ["python", "agent.py", "-p", self.remote_server, "run", "--cmd", cmd],
                capture_output=True, text=True, timeout=30
            )
            gpu_ids = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    gpu_ids.append(int(line.strip()))
            logger.info(f"Detected {len(gpu_ids)} GPUs: {gpu_ids}")
            return gpu_ids
        except Exception as e:
            logger.error(f"GPU detection failed: {e}")
            return list(range(8))

    def assign_to_gpus(self, file_groups: List[List[Dict]], batch_logs_dir: str = None) -> List[Dict]:
        """分配 test_file 组到 GPU slots（round-robin）"""
        available_gpus = self.detect_available_gpus()
        assignments = []
        for idx, group in enumerate(file_groups[:self.max_gpus]):
            gpu_id = available_gpus[idx % len(available_gpus)]
            assignment = {
                "gpu_id": gpu_id,
                "cuda_devices": str(gpu_id),
                "tests": group
            }
            assignments.append(assignment)
        if batch_logs_dir:
            self.log_path = os.path.join(batch_logs_dir, "gpu_scheduler.log")
            os.makedirs(batch_logs_dir, exist_ok=True)
            log_data = {
                "available_gpus": available_gpus,
                "assignments_count": len(assignments),
                "assignments": assignments,
                "assigned_at": datetime.utcnow().isoformat() + "Z"
            }
            with open(self.log_path, "w") as f:
                f.write(json.dumps(log_data, indent=2))
            logger.info(f"GPU assignment log written to {self.log_path}")
        return assignments

    def run_on_gpu(self, assignment: Dict, test_runner_func) -> List[Dict]:
        """在指定 GPU 上执行测试"""
        gpu_id = assignment["gpu_id"]
        cuda_devices = assignment["cuda_devices"]
        tests = assignment["tests"]
        os.environ["CUDA_VISIBLE_DEVICES"] = cuda_devices
        logger.info(f"GPU {gpu_id}: executing {len(tests)} tests")
        results = []
        for test in tests:
            result = test_runner_func(test)
            result["gpu_id"] = gpu_id
            results.append(result)
        return results

def group_by_test_file(tests: List[Dict]) -> List[List[Dict]]:
    """按 test_file 分组测试"""
    file_map = {}
    for test in tests:
        test_file = test.get("test_file", "unknown")
        if test_file not in file_map:
            file_map[test_file] = []
        file_map[test_file].append(test)
    return list(file_map.values())

if __name__ == "__main__":
    config = {"remote_server": "t_h20", "max_gpus": 8}
    scheduler = GPUScheduler(config)
    gpus = scheduler.detect_available_gpus()
    print(f"Available GPUs: {gpus}")