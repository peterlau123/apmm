"""
Bastion daemon进程状态检查脚本
检查agent.py daemon进程是否运行
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# Windows进程检查命令
DAEMON_CHECK_CMD = "wmic process where \"commandline like '%agent.py%'\" get processid,commandline /format:list"

def check_daemon():
    """
    检查daemon进程状态
    
    Returns:
        dict: {"daemon_running": bool, "agent_processes": [...], "count": N}
    """
    try:
        # 检查agent.py进程
        result = subprocess.run(
            DAEMON_CHECK_CMD,
            shell=True,
            capture_output=True, text=True, timeout=10
        )
        
        agent_processes = []
        
        if result.returncode == 0:
            # 解析WMIC输出
            lines = result.stdout.strip().split("\n")
            current_proc = {}
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if "CommandLine=" in line:
                    cmdline = line.split("CommandLine=")[1].strip()
                    if cmdline and "agent.py" in cmdline:
                        current_proc["commandline"] = cmdline
                elif "ProcessId=" in line:
                    pid = line.split("ProcessId=")[1].strip()
                    if pid and current_proc.get("commandline"):
                        current_proc["pid"] = pid
                        agent_processes.append(current_proc)
                        current_proc = {}
        
        daemon_running = len(agent_processes) > 0
        
        return {
            "daemon_running": daemon_running,
            "agent_processes": agent_processes,
            "count": len(agent_processes),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "daemon_running": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="daemon进程检查")
    args = parser.parse_args()
    
    result = check_daemon()
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()