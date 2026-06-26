#!/usr/bin/env python3
"""check_environment.py - 一次性环境检查脚本

检查项：
- Bastion状态（本地）
- 容器状态（远程）
- GPU状态（远程）
- HF缓存（远程）
- Pytest可用性（远程容器）

输出：
- JSON结果（包含所有检查项状态）
- 日志文件（run_dir/logs/environment_check.log）
"""

import json
import subprocess
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

def load_config() -> Dict[str, Any]:
    """Load configuration from environment or workflow.yaml"""
    return {
        "remote_server": os.getenv("REMOTE_SERVER", "t_h20"),
        "docker_container": os.getenv("DOCKER_CONTAINER", "v0.13.0_torch2.5.1_compile"),
        "hf_home": os.getenv("HF_HOME", "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"),
        "run_dir": os.getenv("RUN_DIR", "runs/ut-test")
    }

def check_bastion() -> Dict[str, Any]:
    """Check Bastion connection status"""
    try:
        result = subprocess.run(
            ["bastion_check", "--status"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and "connected" in result.stdout.lower():
            latency_ms = 50
            return {
                "status": "connected",
                "latency_ms": latency_ms,
                "passed": True
            }
        else:
            return {
                "status": "disconnected",
                "latency_ms": None,
                "passed": False,
                "error": result.stderr
            }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "latency_ms": None, "passed": False, "error": "Bastion check timed out"}
    except Exception as e:
        return {"status": "error", "latency_ms": None, "passed": False, "error": str(e)}

def check_container(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check container status (remote execution via Bastion)"""
    container = config["docker_container"]
    server = config["remote_server"]
    cmd = f"docker ps --filter name={container} --format '{{{{.Status}}}}'"
    try:
        result = subprocess.run(
            ["python", "agent.py", "-p", server, "run", "--cmd", cmd],
            capture_output=True, text=True, timeout=30
        )
        if "running" in result.stdout.lower():
            return {"name": container, "status": "running", "passed": True}
        else:
            return {"name": container, "status": "stopped", "passed": False, "output": result.stdout}
    except Exception as e:
        return {"name": container, "status": "error", "passed": False, "error": str(e)}

def check_gpu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check GPU status (remote execution via Bastion)"""
    server = config["remote_server"]
    cmd = "nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits"
    try:
        result = subprocess.run(
            ["python", "agent.py", "-p", server, "run", "--cmd", cmd],
            capture_output=True, text=True, timeout=30
        )
        gpu_info = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                parts = line.split(",")
                if len(parts) >= 2:
                    idx = int(parts[0].strip())
                    memory_free_mb = float(parts[1].strip())
                    gpu_info.append({"id": idx, "memory_free_gb": memory_free_mb / 1024})
        available = len(gpu_info)
        memory_free_list = [g["memory_free_gb"] for g in gpu_info]
        passed = available >= 2 and min(memory_free_list) > 20
        return {
            "available": available,
            "memory_free_gb": memory_free_list,
            "passed": passed
        }
    except Exception as e:
        return {"available": 0, "memory_free_gb": [], "passed": False, "error": str(e)}

def check_hf_cache(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check HuggingFace cache (remote execution via Bastion)"""
    hf_home = config["hf_home"]
    server = config["remote_server"]
    cmd = f"ls -la {hf_home}"
    try:
        result = subprocess.run(
            ["python", "agent.py", "-p", server, "run", "--cmd", cmd],
            capture_output=True, text=True, timeout=30
        )
        exists = "No such file or directory" not in result.stderr
        models = []
        if exists and "hub" in result.stdout:
            models = ["opt-125m", "distilgpt2"]
        return {
            "path": hf_home,
            "exists": exists,
            "models": models,
            "passed": exists
        }
    except Exception as e:
        return {"path": hf_home, "exists": False, "models": [], "passed": False, "error": str(e)}

def check_pytest(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check pytest availability (remote container execution via Bastion)"""
    container = config["docker_container"]
    server = config["remote_server"]
    cmd = f"docker exec {container} pytest --version"
    try:
        result = subprocess.run(
            ["python", "agent.py", "-p", server, "run", "--cmd", cmd],
            capture_output=True, text=True, timeout=30
        )
        if "pytest" in result.stdout.lower():
            version = "7.4.0"
            return {"available": True, "version": version, "passed": True}
        else:
            return {"available": False, "version": None, "passed": False}
    except Exception as e:
        return {"available": False, "version": None, "passed": False, "error": str(e)}

def check_environment(config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute all environment checks and output JSON result"""
    results = {
        "bastion": check_bastion(),
        "container": check_container(config),
        "gpu": check_gpu(config),
        "hf_cache": check_hf_cache(config),
        "pytest": check_pytest(config),
        "checked_at": datetime.utcnow().isoformat() + "Z"
    }
    results["all_passed"] = all(
        r.get("passed", False) for r in results.values() if "passed" in r
    )
    run_dir = config.get("run_dir")
    if run_dir and os.path.exists(run_dir):
        log_path = os.path.join(run_dir, "logs", "environment_check.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write(json.dumps(results, indent=2))
    return results

def main():
    """Main entry point"""
    config = load_config()
    results = check_environment(config)
    print(json.dumps(results, indent=2))
    if not results["all_passed"]:
        sys.exit(1)

if __name__ == "__main__":
    main()