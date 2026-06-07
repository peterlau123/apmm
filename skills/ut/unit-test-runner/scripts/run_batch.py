"""
Runner批次执行脚本
调用现有batch_test_runner.py，输出JSON结果
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# 配置
SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent / ".agents"
VLLM_UT_DIR = SCRIPT_DIR.parent.parent.parent / "vllm" / "2.5.1" / "ut"
# batch_test_runner.py已移动到同目录
BATCH_RUNNER = SCRIPT_DIR / "batch_test_runner.py"

def run_batch(worker: int, tests: list, phase: int, round: int, timeout: int = 120):
    """
    启动pytest批次执行
    
    Returns:
        dict: {"status": "started", "pids": [...], "log_file": "..."}
    """
    # GPU分配
    gpu_map = {1: "0,1", 2: "2,3", 3: "4,5"}
    cuda_devices = gpu_map.get(worker, "0,1")
    
    # 构造batch_id
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_id = f"batch_p{phase}_r{round}_w{worker}_{timestamp}"
    log_file = f"ut_logs/phase{phase}/{batch_id}.log"
    
    result = {
        "batch_id": batch_id,
        "worker": worker,
        "phase": phase,
        "round": round,
        "cuda_devices": cuda_devices,
        "tests": tests,
        "tests_count": len(tests),
        "timeout": timeout,
        "log_file": log_file,
        "started_at": datetime.now().isoformat()
    }
    
    # 调用同目录脚本
    if BATCH_RUNNER.exists():
        # 构造命令
        test_str = " ".join(tests)
        cmd = [
            sys.executable, str(BATCH_RUNNER),
            "--tests", test_str,
            "--worker", str(worker),
            "--cuda-devices", cuda_devices,
            "--timeout", str(timeout),
            "--log-file", log_file,
            "--background"
        ]
        
        try:
            proc_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc_result.returncode == 0:
                result["status"] = "started"
                result["output"] = proc_result.stdout[:500]
            else:
                result["status"] = "error"
                result["error"] = proc_result.stderr[:500]
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["error"] = "Command timeout after 30s"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
    else:
        # 脚本不存在，返回模拟结果
        result["status"] = "mock"
        result["message"] = "batch_test_runner.py not found, returning mock result"
    
    return result

def main():
    parser = argparse.ArgumentParser(description="Runner批次执行脚本")
    parser.add_argument("--worker", type=int, required=True, help="Worker编号 (1-3)")
    parser.add_argument("--tests", nargs="+", required=True, help="测试列表")
    parser.add_argument("--phase", type=int, default=1, help="Phase编号")
    parser.add_argument("--round", type=int, default=1, help="Round编号")
    parser.add_argument("--timeout", type=int, default=120, help="超时秒数")
    
    args = parser.parse_args()
    
    result = run_batch(args.worker, args.tests, args.phase, args.round, args.timeout)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()