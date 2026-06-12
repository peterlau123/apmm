#!/usr/bin/env python3
"""
并发执行批次测试脚本

支持两种并发模式：
1. pytest-xdist：普通测试多进程并行
2. GPU分区：distributed测试多GPU并行

使用方法：
    python parallel_batch_executor.py --batch-id batch_001 --tests tests/xxx.py
    python parallel_batch_executor.py --distributed --gpus 0,1,2,3
"""

import json
import argparse
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

# 路径配置 - 从脚本目录推断
VLLM_PATH = "/gpfs/gcsp/M2.7_verify/vllm"
_SCRIPT_DIR = Path(__file__).parent
_WORKSPACE = _SCRIPT_DIR.parent.parent.parent.parent
LOG_DIR = _WORKSPACE / "tasks" / "ut" / "test_analysis" / "ut_logs"
CONTAINER = "v0.13.0_torch2.5.1_compile"

# 并发配置
XDIST_WORKERS = 4  # pytest-xdist worker数量


def is_distributed_test(test_node: str) -> bool:
    """检测是否为 distributed 测试"""
    patterns = [
        "tests/distributed/",
        "test_pipeline_parallel",
        "test_tensor_parallel",
        "test_distributed",
        "MULTI_GPU",
        "world_size"
    ]
    return any(p in test_node for p in patterns)


def group_tests_by_type(tests: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """按测试类型分组"""
    distributed = []
    normal = []
    
    for test in tests:
        if is_distributed_test(test.get("test_node", "")):
            distributed.append(test)
        else:
            normal.append(test)
    
    return distributed, normal


def build_pytest_command(
    tests: List[str],
    workers: int = XDIST_WORKERS,
    distributed: bool = False,
    gpu_group: Optional[List[int]] = None,
    master_port: Optional[int] = None
) -> str:
    """构建 pytest 命令"""
    
    test_list = " ".join(tests)
    
    if distributed and gpu_group:
        # distributed 测试：GPU分区 + 分布式环境变量
        cuda_devices = ",".join(map(str, gpu_group))
        world_size = len(gpu_group)
        port = master_port or 29500
        
        cmd = f"""
CUDA_VISIBLE_DEVICES={cuda_devices} \
MASTER_ADDR=localhost \
MASTER_PORT={port} \
WORLD_SIZE={world_size} \
pytest -n 1 -q --tb=long {test_list}
"""
    else:
        # 普通测试：pytest-xdist
        cmd = f"pytest -n {workers} -q --tb=long {test_list}"
    
    return cmd.strip()


def execute_batch_remote(
    tests: List[str],
    batch_id: str,
    workers: int = XDIST_WORKERS,
    distributed: bool = False,
    gpu_group: Optional[List[int]] = None,
    master_port: Optional[int] = None,
    timeout: int = 600
) -> Dict:
    """通过 agent.py 远程执行 pytest"""
    
    log_file = f"ut_logs/{batch_id}.log"
    pytest_cmd = build_pytest_command(tests, workers, distributed, gpu_group, master_port)
    
    # Docker exec 命令
    docker_cmd = f"""
sudo docker exec {CONTAINER} bash -c '
cd {VLLM_PATH} && \
{pytest_cmd} \
2>&1 | tee {log_file}
'
"""
    
    # 通过 agent.py 执行
    agent_cmd = [
        "python", str(_WORKSPACE / "tools" / "agent.py"),
        "-p", "t_h20",
        "run", "--timeout", str(timeout),
        docker_cmd.strip()
    ]
    
    start_time = datetime.now()
    
    try:
        result = subprocess.run(
            agent_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 60
        )
        
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        # 解析 pytest 输出
        passed, failed, error = parse_pytest_output(result.stdout)
        
        return {
            "batch_id": batch_id,
            "status": "completed",
            "passed": passed,
            "failed": failed,
            "error": error,
            "duration_ms": duration_ms,
            "log_file": log_file,
            "exit_code": result.returncode,
            "output": result.stdout
        }
        
    except subprocess.TimeoutExpired:
        return {
            "batch_id": batch_id,
            "status": "timeout",
            "error": "执行超时",
            "duration_ms": timeout * 1000
        }
    except Exception as e:
        return {
            "batch_id": batch_id,
            "status": "error",
            "error": str(e)
        }


def execute_parallel_batches(
    batch_info: Dict,
    available_gpus: List[int]
) -> List[Dict]:
    """并行执行多个批次"""
    
    tests = batch_info.get("tests", [])
    distributed_tests, normal_tests = group_tests_by_type(tests)
    
    results = []
    
    # 1. 普通测试：pytest-xdist
    if normal_tests:
        test_nodes = [t["test_node"] for t in normal_tests]
        batch_id = batch_info.get("batch_id", f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        
        print(f"[普通测试] 执行 {len(normal_tests)} 个测试 (pytest-xdist, workers={XDIST_WORKERS})")
        
        result = execute_batch_remote(
            tests=test_nodes,
            batch_id=batch_id,
            workers=XDIST_WORKERS,
            timeout=600
        )
        results.append(result)
    
    # 2. distributed 测试：GPU分区并行
    if distributed_tests and len(available_gpus) >= 2:
        # 分配 GPU 组
        gpu_groups = allocate_gpu_groups(available_gpus, distributed_tests)
        
        print(f"[distributed测试] 执行 {len(distributed_tests)} 个测试 (GPU分区并行)")
        
        # 并行启动多个 pytest 进程
        processes = []
        for i, (gpu_group, test) in enumerate(gpu_groups):
            batch_id = f"{batch_info.get('batch_id', 'batch')}_dist_{i}"
            port = 29500 + i
            
            # 使用相对路径（不硬编码）
            script_dir = Path(__file__).parent
            agent_path = script_dir.parent.parent.parent / "tools" / "agent.py"
            
            # 后台执行
            proc = subprocess.Popen(
                [
                    "python", str(agent_path),
                    "-p", "t_h20",
                    "run", "--timeout", "600",
                    f"""
sudo docker exec {CONTAINER} bash -c '
cd {VLLM_PATH} && \
CUDA_VISIBLE_DEVICES={','.join(map(str, gpu_group))} \
MASTER_ADDR=localhost \
MASTER_PORT={port} \
WORLD_SIZE={len(gpu_group)} \
pytest -n 1 -q --tb=long {test["test_node"]} \
2>&1 | tee ut_logs/{batch_id}.log
'
"""
                ],
                capture_output=True,
                text=True
            )
            processes.append((batch_id, proc, test))
        
        # 等待所有进程完成
        for batch_id, proc, test in processes:
            proc.wait()
            output = proc.stdout.read()
            passed, failed, error = parse_pytest_output(output)
            
            results.append({
                "batch_id": batch_id,
                "test_node": test["test_node"],
                "status": "completed",
                "passed": passed,
                "failed": failed,
                "error": error,
                "exit_code": proc.returncode
            })
    
    elif distributed_tests and len(available_gpus) < 2:
        # GPU 不足，标记为 error
        for test in distributed_tests:
            results.append({
                "test_node": test["test_node"],
                "status": "error",
                "error_category": "E",
                "error_message": f"distributed 测试需要 GPU ≥ 2，当前可用 GPU: {len(available_gpus)}",
                "available_gpus": len(available_gpus),
                "required_gpus": 2
            })
    
    return results


def allocate_gpu_groups(
    available_gpus: List[int],
    distributed_tests: List[Dict]
) -> List[Tuple[List[int], Dict]]:
    """为 distributed 测试分配 GPU 组"""
    
    groups = []
    gpu_per_test = 2  # 每个 distributed 测试分配 2 个 GPU
    
    for i, test in enumerate(distributed_tests):
        start_idx = i * gpu_per_test
        end_idx = start_idx + gpu_per_test
        
        if end_idx <= len(available_gpus):
            gpu_group = available_gpus[start_idx:end_idx]
            groups.append((gpu_group, test))
        else:
            # GPU 不足，跳过
            break
    
    return groups


def parse_pytest_output(output: str) -> Tuple[int, int, int]:
    """解析 pytest 输出，提取 passed/failed/error 数量"""
    
    passed = 0
    failed = 0
    error = 0
    
    for line in output.splitlines():
        if " passed" in line:
            # 提取数字，如 "42 passed"
            parts = line.split()
            for part in parts:
                if part.isdigit():
                    passed = int(part)
                    break
        if " failed" in line:
            parts = line.split()
            for part in parts:
                if part.isdigit():
                    failed = int(part)
                    break
        if " error" in line:
            parts = line.split()
            for part in parts:
                if part.isdigit():
                    error = int(part)
                    break
    
    # 如果没找到，尝试从 summary 行解析
    if passed == 0 and failed == 0 and error == 0:
        # 解析 "= X passed, Y failed, Z errors =" 格式
        for line in output.splitlines():
            if "=" in line and "passed" in line:
                import re
                match = re.search(r"(\d+) passed", line)
                if match:
                    passed = int(match.group(1))
                match = re.search(r"(\d+) failed", line)
                if match:
                    failed = int(match.group(1))
                match = re.search(r"(\d+) error", line)
                if match:
                    error = int(match.group(1))
    
    return passed, failed, error


def main():
    parser = argparse.ArgumentParser(description="并发执行批次测试")
    
    parser.add_argument("--batch-id", type=str, required=True, help="批次ID")
    parser.add_argument("--tests", type=str, nargs="+", help="测试节点列表")
    parser.add_argument("--batch-file", type=str, help="批次清单JSON文件")
    parser.add_argument("--workers", type=int, default=XDIST_WORKERS, help="xdist worker数量")
    parser.add_argument("--distributed", action="store_true", help="distributed测试模式")
    parser.add_argument("--gpus", type=str, help="可用GPU列表，如 0,1,2,3")
    parser.add_argument("--timeout", type=int, default=600, help="超时时间（秒）")
    parser.add_argument("--output", type=str, help="结果输出文件")
    
    args = parser.parse_args()
    
    # 加载测试列表
    if args.batch_file:
        batch_info = json.loads(Path(args.batch_file).read_text(encoding="utf-8"))
    elif args.tests:
        batch_info = {
            "batch_id": args.batch_id,
            "tests": [{"test_node": t} for t in args.tests]
        }
    else:
        print("错误: 需要提供 --tests 或 --batch-file")
        return
    
    # 解析可用GPU
    available_gpus = []
    if args.gpus:
        available_gpus = [int(g) for g in args.gpus.split(",")]
    elif args.distributed:
        # 需要检测GPU
        print("警告: distributed 测试需要指定 --gpus")
    
    # 执行
    results = execute_parallel_batches(batch_info, available_gpus)
    
    # 输出结果
    output = {
        "batch_id": args.batch_id,
        "executed_at": datetime.now().isoformat(),
        "results": results,
        "summary": {
            "total_tests": len(batch_info.get("tests", [])),
            "total_passed": sum(r.get("passed", 0) for r in results),
            "total_failed": sum(r.get("failed", 0) for r in results),
            "total_error": sum(r.get("error", 0) for r in results)
        }
    }
    
    print(json.dumps(output, indent=2, ensure_ascii=False))
    
    if args.output:
        Path(args.output).write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


if __name__ == "__main__":
    main()