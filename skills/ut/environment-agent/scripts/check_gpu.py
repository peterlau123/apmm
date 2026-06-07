"""
Environment GPU状态检查脚本
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

# UT测试进程关键词
UT_PROCESS_KEYWORDS = ["pytest", "python -m pytest", "vllm"]

def check_gpu():
    """
    检查GPU状态
    
    Returns:
        dict: {"idle_gpus": [...], "occupied_gpus": [...], 
               "intrusion_pids": [...], "healthy": bool}
    """
    if not AGENT_PY.exists():
        return {
            "error": "agent.py not found",
            "idle_gpus": [],
            "occupied_gpus": [],
            "intrusion_pids": [],
            "healthy": False,
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # 获取GPU使用情况
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
             "--timeout", "30",
             "nvidia-smi --query-gpu=index,memory.free,utilization.gpu --format=csv,noheader"],
            capture_output=True, text=True, timeout=60
        )
        
        idle_gpus = []
        occupied_gpus = []
        
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(",")
                    if len(parts) >= 3:
                        gpu_id = parts[0].strip()
                        try:
                            memory_free = int(parts[1].strip().split()[0])
                            gpu_util = int(parts[2].strip().split()[0])
                            
                            # 判断空闲：内存>100GB且利用率<5%
                            if memory_free > 100000 and gpu_util < 5:
                                idle_gpus.append(gpu_id)
                            else:
                                occupied_gpus.append(gpu_id)
                        except:
                            pass
        
        # 获取占用GPU的进程
        intrusion_pids = []
        if occupied_gpus:
            for gpu_id in occupied_gpus:
                proc_result = subprocess.run(
                    [sys.executable, str(AGENT_PY), "-p", "t_h20", "run",
                     "--timeout", "30",
                     f"nvidia-smi --id={gpu_id} --query-compute-apps=pid,process_name --format=csv,noheader"],
                    capture_output=True, text=True, timeout=60
                )
                
                if proc_result.returncode == 0:
                    for line in proc_result.stdout.strip().split("\n"):
                        if line:
                            parts = line.split(",")
                            if len(parts) >= 2:
                                pid = parts[0].strip()
                                proc_name = parts[1].strip()
                                
                                # 检查是否为UT进程
                                is_ut = any(kw in proc_name for kw in UT_PROCESS_KEYWORDS)
                                if not is_ut:
                                    intrusion_pids.append({
                                        "pid": pid,
                                        "gpu": gpu_id,
                                        "process": proc_name
                                    })
        
        healthy = len(intrusion_pids) == 0 and len(idle_gpus) >= 2
        
        return {
            "idle_gpus": idle_gpus,
            "occupied_gpus": occupied_gpus,
            "intrusion_pids": intrusion_pids,
            "healthy": healthy,
            "total_gpus": 8,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "idle_gpus": [],
            "occupied_gpus": [],
            "intrusion_pids": [],
            "healthy": False,
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="GPU状态检查")
    args = parser.parse_args()
    
    result = check_gpu()
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()