"""
Bastion 连接健康检查脚本
Ping t_h20和t_ascend，输出JSON格式结果
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent.parent / "agent.py"

# 监控的目标机器
TARGETS = ["t_h20", "t_ascend"]

def ping_target(target: str, timeout: int = 10):
    """
    Ping指定目标机器
    
    Args:
        target: 目标机器名称 (t_h20, t_ascend)
        timeout: 超时秒数
    
    Returns:
        dict: {"status": "connected/unstable/disconnect", "delay_ms": N}
    """
    if not AGENT_PY.exists():
        return {
            "target": target,
            "status": "error",
            "error": "agent.py not found",
            "timestamp": datetime.now().isoformat()
        }
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", target, "ping"],
            capture_output=True, text=True, timeout=timeout
        )
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        if result.returncode == 0 and ("running" in result.stdout.lower() or "pong" in result.stdout.lower()):
            # 判断稳定状态
            if elapsed_ms > 5000:
                status = "unstable"
            else:
                status = "connected"
            
            return {
                "target": target,
                "status": status,
                "delay_ms": elapsed_ms,
                "output": result.stdout[:100],
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "target": target,
                "status": "disconnect",
                "delay_ms": elapsed_ms,
                "error": result.stderr[:100] if result.stderr else "no pong response",
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "target": target,
            "status": "disconnect",
            "delay_ms": elapsed_ms,
            "error": f"timeout after {timeout}s",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "target": target,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def check_all_connections():
    """
    检查所有目标机器的连接状态
    
    Returns:
        dict: {"t_h20": {...}, "t_ascend": {...}, "healthy": bool}
    """
    results = {}
    
    for target in TARGETS:
        results[target] = ping_target(target)
    
    # 判断整体健康状态
    healthy = all(r.get("status") == "connected" for r in results.values())
    
    results["healthy"] = healthy
    results["timestamp"] = datetime.now().isoformat()
    
    return results

def main():
    parser = argparse.ArgumentParser(description="连接健康检查")
    parser.add_argument("--target", type=str, default=None, help="指定目标机器")
    parser.add_argument("--timeout", type=int, default=10, help="超时秒数")
    
    args = parser.parse_args()
    
    if args.target:
        result = ping_target(args.target, args.timeout)
    else:
        result = check_all_connections()
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()