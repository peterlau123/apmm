"""
Dependency Resolver - 检查依赖脚本
检查远程容器是否已安装指定依赖
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
TOOLS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / "tools"

# 远程执行配置
AGENT_PY = TOOLS_DIR / "agent.py"
TARGET_SERVER = "t_h20"  # 测试机器，检查容器内依赖

def check_dependency_on_remote(
    package_name: str,
    container: str = "v0.13.0_torch2.5.1_compile"
) -> dict:
    """
    检查远程容器是否已安装指定依赖
    
    Args:
        package_name: 包名
        container: Docker 容器名
        
    Returns:
        dict: 检查结果
    """
    # 构建 pip show 命令
    pip_cmd = f"pip show {package_name}"
    
    # 通过 docker exec 在容器内执行
    remote_cmd = f"sudo docker exec {container} bash -c '{pip_cmd}'"
    
    # 通过 agent.py 在远程执行
    full_cmd = f"python {AGENT_PY} -p {TARGET_SERVER} run --timeout 30 \"{remote_cmd}\""
    
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(TOOLS_DIR)
        )
        
        # 检查是否安装
        if result.returncode == 0 and "Name:" in result.stdout:
            # 解析版本信息
            version = None
            for line in result.stdout.splitlines():
                if line.startswith("Version:"):
                    version = line.split(":")[1].strip()
                    break
            
            return {
                "installed": True,
                "package": package_name,
                "version": version,
                "location": "container",
                "container": container,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "installed": False,
                "package": package_name,
                "error": "Package not found",
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        return {
            "installed": False,
            "package": package_name,
            "error": "Check timed out",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "installed": False,
            "package": package_name,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def check_gpu_availability(gpu_count: int = 1) -> dict:
    """
    检查 GPU 可用性
    
    Args:
        gpu_count: 需要的 GPU 数量
        
    Returns:
        dict: 检查结果
    """
    # 构建 nvidia-smi 命令
    nvidia_cmd = "nvidia-smi --query-gpu=index,memory.free --format=csv,noheader"
    
    # 通过 agent.py 在远程执行
    full_cmd = f"python {AGENT_PY} -p {TARGET_SERVER} run --timeout 30 \"{nvidia_cmd}\""
    
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(TOOLS_DIR)
        )
        
        if result.returncode == 0:
            # 解析 GPU 信息
            available_gpus = []
            for line in result.stdout.splitlines():
                parts = line.split(",")
                if len(parts) >= 2:
                    gpu_id = parts[0].strip()
                    memory_free = int(parts[1].strip().split()[0])  # MB
                    if memory_free > 10000:  # 至少 10GB 可用
                        available_gpus.append({
                            "id": gpu_id,
                            "memory_free_mb": memory_free
                        })
            
            return {
                "available": len(available_gpus) >= gpu_count,
                "gpu_count_needed": gpu_count,
                "available_gpus": available_gpus,
                "total_gpus": len(available_gpus),
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "available": False,
                "error": result.stderr,
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="Dependency Resolver - 检查依赖")
    parser.add_argument("--package", type=str, default=None, help="检查的包名")
    parser.add_argument("--gpu", type=int, default=None, help="检查 GPU 可用数量")
    parser.add_argument("--container", type=str, default="v0.13.0_torch2.5.1_compile",
                        help="Docker 容器名")
    
    args = parser.parse_args()
    
    if args.package:
        # 检查包依赖
        result = check_dependency_on_remote(args.package, args.container)
        
        if result["installed"]:
            print(f"[OK] {args.package} installed (version: {result.get('version', 'unknown')})")
        else:
            print(f"[WARN] {args.package} not installed")
        
        print(json.dumps(result, indent=2))
    
    if args.gpu:
        # 检查 GPU 可用性
        result = check_gpu_availability(args.gpu)
        
        if result["available"]:
            print(f"[OK] {result['total_gpus']} GPUs available (need {args.gpu})")
        else:
            print(f"[WARN] Not enough GPUs available")
        
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()