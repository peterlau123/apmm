#!/usr/bin/env python3
"""检查远程服务器可用 GPU 数量"""

import subprocess
import json
import sys
from pathlib import Path

# 路径配置 - 从脚本目录推断
AGENT_PATH = Path(__file__).parent.parent.parent.parent.parent / "tools" / "agent.py"


def check_gpus_via_agent(timeout=30):
    """通过 agent.py 检查远程 GPU 可用性"""
    
    # GPU 检测命令
    gpu_cmd = '''
sudo docker exec v0.13.0_torch2.5.1_compile bash -c "
nvidia-smi --query-gpu=index,memory.used,memory.total --format csv,noheader | 
awk -F, '{usage=$2/$3; if (usage < 0.1) print \"GPU \"$1\": available\"}'
"
'''
    
    cmd = [
        "python", str(AGENT_PATH),
        "-p", "t_h20",
        "run", "--timeout", str(timeout),
        gpu_cmd.strip()
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        
        # 解析输出
        available_gpus = []
        for line in result.stdout.splitlines():
            if "available" in line.lower():
                # 提取 GPU index
                parts = line.split(":")
                if len(parts) >= 1:
                    gpu_idx = parts[0].replace("GPU", "").strip()
                    available_gpus.append(int(gpu_idx))
        
        return {
            "available_gpus": len(available_gpus),
            "gpu_indices": available_gpus,
            "raw_output": result.stdout,
            "error": None
        }
        
    except subprocess.TimeoutExpired:
        return {
            "available_gpus": 0,
            "gpu_indices": [],
            "raw_output": "",
            "error": "timeout"
        }
    except Exception as e:
        return {
            "available_gpus": 0,
            "gpu_indices": [],
            "raw_output": "",
            "error": str(e)
        }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="检查远程 GPU 可用性")
    parser.add_argument("--timeout", type=int, default=30, help="超时时间（秒）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    args = parser.parse_args()
    
    result = check_gpus_via_agent(timeout=args.timeout)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["error"]:
            print(f"错误: {result['error']}")
        else:
            print(f"可用 GPU 数量: {result['available_gpus']}")
            if result['gpu_indices']:
                print(f"GPU 索引: {result['gpu_indices']}")

if __name__ == "__main__":
    main()