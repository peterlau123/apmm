#!/usr/bin/env python3
"""
检查Agent状态（apmm版本）
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

PROJECT_DIR = Path("D:/workspace/apmm")
AGENTS_DIR = PROJECT_DIR / ".agents"

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except:
        return {}

def check_agent_status(agent_id):
    """检查单个Agent状态"""
    status_file = AGENTS_DIR / agent_id / "status.json"
    heartbeat_file = AGENTS_DIR / agent_id / "heartbeat.json"
    
    status = read_json(status_file)
    heartbeat = read_json(heartbeat_file)
    
    # 检查心跳超时
    heartbeat_ok = False
    if heartbeat.get("timestamp"):
        try:
            ts = heartbeat["timestamp"].replace("Z", "+00:00")
            last_beat = datetime.fromisoformat(ts)
            elapsed = (datetime.now(timezone.utc) - last_beat).total_seconds()
            heartbeat_ok = elapsed < 60
        except:
            pass
    
    return {
        "status": status.get("status", "unknown"),
        "heartbeat_ok": heartbeat_ok,
        "last_update": status.get("last_update", "")
    }

def main():
    # 读取配置
    config = read_json(AGENTS_DIR / "config.json")
    
    print("=" * 60)
    print("Agent Status Check (apmm)")
    print("=" * 60)
    
    agents = config.get("agents", {})
    
    for agent_id in agents:
        if agent_id == "supervisor":
            continue
        
        # 跳过disabled
        if agents[agent_id].get("enabled") is False:
            print(f"{agent_id:20} DISABLED")
            continue
        
        info = check_agent_status(agent_id)
        
        status_icon = "✓" if info["status"] in ["running", "active"] else "✗"
        heartbeat_icon = "✓" if info["heartbeat_ok"] else "✗"
        
        print(f"{agent_id:20} {status_icon} {info['status']:10} 心跳:{heartbeat_icon}")
    
    # 检查global_state
    global_state = read_json(AGENTS_DIR / "global_state.json")
    if global_state:
        print("\n--- Global State ---")
        print(f"Last update: {global_state.get('last_update', 'N/A')}")
        
        test_progress = global_state.get("test_progress", {})
        if test_progress:
            completed = test_progress.get("completed", 0)
            passed = test_progress.get("passed", 0)
            failed = test_progress.get("failed", 0)
            print(f"Tests: {completed} completed, {passed} passed, {failed} failed")

if __name__ == "__main__":
    main()