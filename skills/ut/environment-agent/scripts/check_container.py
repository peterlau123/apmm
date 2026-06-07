"""
Environment 容器状态检查脚本
输出JSON格式结果
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent / "agent.py"

# 监控的容器 - 单元测试运行容器
CONTAINERS = [
    "v0.13.0_torch2.5.1_compile",  # 单元测试运行容器
]

def check_container():
    """
    检查容器状态
    
    Returns:
        dict: {"containers": [...], "healthy": bool}
    """
    if not AGENT_PY.exists():
        return {
            "error": "agent.py not found",
            "containers": [],
            "healthy": False,
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # 获取容器列表
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
             "--timeout", "30",
             "sudo docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}'"],
            capture_output=True, text=True, timeout=60
        )
        
        containers = []
        
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        name = parts[0].strip()
                        status = parts[1].strip()
                        image = parts[2].strip()
                        
                        if name in CONTAINERS:
                            # 解析状态
                            is_running = "Up" in status
                            containers.append({
                                "name": name,
                                "status": "running" if is_running else "stopped",
                                "docker_status": status,
                                "image": image,
                                "healthy": is_running
                            })
        
        # 检查是否有缺失的容器
        found_names = [c["name"] for c in containers]
        for expected in CONTAINERS:
            if expected not in found_names:
                containers.append({
                    "name": expected,
                    "status": "not_found",
                    "healthy": False
                })
        
        healthy = all(c.get("healthy", False) for c in containers)
        
        return {
            "containers": containers,
            "healthy": healthy,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "containers": [],
            "healthy": False,
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="容器状态检查")
    args = parser.parse_args()
    
    result = check_container()
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()