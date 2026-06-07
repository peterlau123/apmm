"""
Environment 磁盘空间检查脚本
检查/gpfs共享存储空间
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent / "agent.py"

# 磁盘路径
DISK_PATH = "/gpfs/gcsp/M2.7_verify"

def check_disk():
    """
    检查磁盘空间
    
    Returns:
        dict: {"path": "...", "used_percent": N, "available_gb": N, "warning": bool}
    """
    if not AGENT_PY.exists():
        return {
            "error": "agent.py not found",
            "path": DISK_PATH,
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # 获取磁盘使用情况
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_ascend", "run",
             "--timeout", "30",
             f"df -h {DISK_PATH} | tail -1"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            line = result.stdout.strip()
            parts = line.split()
            
            if len(parts) >= 5:
                # 解析df输出: Filesystem Size Used Avail Use% Mounted
                total = parts[1]
                used = parts[2]
                available = parts[3]
                use_percent = int(parts[4].replace("%", ""))
                
                # 转换为GB
                total_gb = parse_size_to_gb(total)
                used_gb = parse_size_to_gb(used)
                available_gb = parse_size_to_gb(available)
                
                return {
                    "path": DISK_PATH,
                    "total": total,
                    "total_gb": total_gb,
                    "used": used,
                    "used_gb": used_gb,
                    "available": available,
                    "available_gb": available_gb,
                    "used_percent": use_percent,
                    "warning": use_percent > 90,
                    "critical": use_percent > 95,
                    "timestamp": datetime.now().isoformat()
                }
        
        return {
            "error": "Failed to parse df output",
            "output": result.stdout[:200],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "path": DISK_PATH,
            "timestamp": datetime.now().isoformat()
        }

def parse_size_to_gb(size_str: str) -> float:
    """解析大小字符串为GB"""
    size_str = size_str.strip()
    if size_str.endswith("T"):
        return float(size_str[:-1]) * 1000
    elif size_str.endswith("G"):
        return float(size_str[:-1])
    elif size_str.endswith("M"):
        return float(size_str[:-1]) / 1000
    elif size_str.endswith("K"):
        return float(size_str[:-1]) / 1000000
    else:
        try:
            return float(size_str) / 1000000000
        except:
            return 0

def main():
    parser = argparse.ArgumentParser(description="磁盘空间检查")
    args = parser.parse_args()
    
    result = check_disk()
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()