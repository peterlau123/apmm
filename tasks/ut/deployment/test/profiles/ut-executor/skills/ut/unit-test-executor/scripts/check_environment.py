"""
Runner环境检查脚本
检查Bastion连接、GPU状态、CPU负载、容器验证
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent / "agent.py"

def check_bastion():
    """检查Bastion连接"""
    if not AGENT_PY.exists():
        return {
            "bastion": "unknown",
            "t_h20": "unknown",
            "error": "agent.py not found",
            "last_check": datetime.now().isoformat()
        }
    
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "ping"],
            capture_output=True, text=True, timeout=10
        )
        
        connected = result.returncode == 0
        
        return {
            "bastion": "connected" if connected else "disconnected",
            "t_h20": connected,
            "output": result.stdout[:100] if result.stdout else "",
            "last_check": datetime.now().isoformat()
        }
    except subprocess.TimeoutExpired:
        return {
            "bastion": "timeout",
            "t_h20": "timeout",
            "error": "Ping timeout after 10s",
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "bastion": "error",
            "t_h20": "error",
            "error": str(e),
            "last_check": datetime.now().isoformat()
        }

def check_gpu_mock():
    """模拟GPU检查（当无法SSH时）"""
    return {
        "idle_gpus": ["0", "2", "4"],
        "occupied_gpus": ["1", "3", "5"],
        "total_gpus": 8,
        "mode": "mock",
        "last_check": datetime.now().isoformat()
    }

def check_gpu():
    """检查GPU状态（通过SSH）"""
    if not AGENT_PY.exists():
        return check_gpu_mock()
    
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
             "--timeout", "30",
             "nvidia-smi --query-gpu=index,memory.free --format=csv,noheader"],
            capture_output=True, text=True, timeout=60
        )
        
        idle_gpus = []
        occupied_gpus = []
        
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        gpu_id = parts[0].strip()
                        try:
                            memory_free = int(parts[1].strip().split()[0])
                            if memory_free > 100000:  # >100GB free
                                idle_gpus.append(gpu_id)
                            else:
                                occupied_gpus.append(gpu_id)
                        except:
                            pass
        
        return {
            "idle_gpus": idle_gpus,
            "occupied_gpus": occupied_gpus,
            "total_gpus": 8,
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "idle_gpus": [],
            "occupied_gpus": [],
            "total_gpus": 8,
            "last_check": datetime.now().isoformat()
        }

def check_cpu_mock():
    """模拟CPU检查"""
    return {
        "cpu_usage": 45,
        "overloaded": False,
        "mode": "mock",
        "last_check": datetime.now().isoformat()
    }

def check_cpu():
    """检查CPU负载"""
    if not AGENT_PY.exists():
        return check_cpu_mock()
    
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
             "--timeout", "30",
             "cat /proc/loadavg"],
            capture_output=True, text=True, timeout=60
        )
        
        cpu_usage = 0
        if result.returncode == 0:
            # 解析loadavg: 1.23 2.45 3.67 4/89 12345
            parts = result.stdout.strip().split()
            if parts:
                load = float(parts[0])  # 1分钟平均负载
                # 简化估算，假设8核
                cpu_usage = min(100, load * 12.5)
        
        return {
            "cpu_usage": round(cpu_usage, 1),
            "overloaded": cpu_usage > 85,
            "load_avg": result.stdout.strip() if result.returncode == 0 else "",
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "cpu_usage": 0,
            "overloaded": False,
            "last_check": datetime.now().isoformat()
        }

# 正确的容器名称配置
CORRECT_CONTAINER = "v0.13.0_torch2.5.1_compile"

def check_container():
    """验证当前进入的容器是否正确"""
    if not AGENT_PY.exists():
        return {
            "container": "unknown",
            "correct": False,
            "expected": CORRECT_CONTAINER,
            "mode": "mock",
            "last_check": datetime.now().isoformat()
        }
    
    try:
        # 获取所有运行中的v0.13.0容器
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
             "--timeout", "30",
             "sudo docker ps --format '{{.Names}}' | grep v0.13.0"],
            capture_output=True, text=True, timeout=60
        )
        
        running_containers = []
        if result.returncode == 0:
            running_containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        
        # 检查是否有正确的容器
        correct_container_running = CORRECT_CONTAINER in running_containers
        
        return {
            "running_containers": running_containers,
            "correct_container_running": correct_container_running,
            "expected": CORRECT_CONTAINER,
            "correct": correct_container_running,
            "warning": f"请使用 {CORRECT_CONTAINER}" if not correct_container_running else None,
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "container": "error",
            "correct": False,
            "expected": CORRECT_CONTAINER,
            "last_check": datetime.now().isoformat()
        }

def check_all():
    """检查所有环境状态"""
    bastion = check_bastion()
    gpu = check_gpu()
    cpu = check_cpu()
    container = check_container()
    
    healthy = bastion["bastion"] == "connected" and not cpu.get("overloaded", False) and container.get("correct", False)
    
    return {
        "bastion": bastion,
        "gpu": gpu,
        "cpu": cpu,
        "container": container,
        "healthy": healthy,
        "timestamp": datetime.now().isoformat()
    }

def main():
    parser = argparse.ArgumentParser(description="Runner环境检查脚本")
    parser.add_argument("--bastion", action="store_true", help="仅检查bastion")
    parser.add_argument("--gpu", action="store_true", help="仅检查GPU")
    parser.add_argument("--cpu", action="store_true", help="仅检查CPU")
    parser.add_argument("--container", action="store_true", help="仅检查容器")
    parser.add_argument("--all", action="store_true", help="检查所有")
    
    args = parser.parse_args()
    
    if args.bastion:
        result = check_bastion()
    elif args.gpu:
        result = check_gpu()
    elif args.cpu:
        result = check_cpu()
    elif args.container:
        result = check_container()
    else:
        result = check_all()
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()