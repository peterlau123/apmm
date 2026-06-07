"""
Runner状态更新脚本
更新.agents/runner/status.json和心跳
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
STATUS_FILE = AGENTS_DIR / "runner" / "status.json"
HEARTBEAT_FILE = AGENTS_DIR / "runner" / "heartbeat.json"

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text())
    except:
        return {}

def write_json(file_path, data):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(json.dumps(data, indent=2))

def update_status(stats: dict, current_task: dict = None):
    """
    更新Runner状态
    
    Args:
        stats: {"passed": N, "failed": N, ...}
        current_task: {"phase": 1, "round": 1, "description": "..."}
    """
    # 读取现有状态
    status = read_json(STATUS_FILE)
    
    # 初始化
    if not status:
        status = {
            "agent_id": "unit-test-runner",
            "agent_type": "claude-code",
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
    
    # 更新统计
    status["statistics"] = {
        "tests_completed": stats.get("completed", 0),
        "tests_passed": stats.get("passed", 0),
        "tests_failed": stats.get("failed", 0),
        "tests_error": stats.get("error", 0),
        "tests_skipped": stats.get("skipped", 0),
    }
    
    # 更新当前任务
    if current_task:
        status["current_task"] = current_task
    
    # 更新时间
    status["last_update"] = datetime.now().isoformat()
    
    # 写入文件
    write_json(STATUS_FILE, status)
    
    return {"status": "updated", "file": str(STATUS_FILE)}

def update_heartbeat():
    """更新心跳"""
    heartbeat = {"timestamp": datetime.now().isoformat()}
    write_json(HEARTBEAT_FILE, heartbeat)
    return heartbeat

def main():
    parser = argparse.ArgumentParser(description="Runner状态更新脚本")
    parser.add_argument("--stats", type=str, help="JSON stats字符串")
    parser.add_argument("--phase", type=int, default=None, help="Phase编号")
    parser.add_argument("--round", type=int, default=None, help="Round编号")
    parser.add_argument("--description", type=str, default="", help="任务描述")
    parser.add_argument("--status", type=str, default=None, help="Agent状态")
    parser.add_argument("--heartbeat", action="store_true", help="仅更新心跳")
    
    args = parser.parse_args()
    
    if args.heartbeat:
        result = update_heartbeat()
    elif args.status:
        # 仅更新状态字段
        status = read_json(STATUS_FILE)
        status["status"] = args.status
        status["last_update"] = datetime.now().isoformat()
        write_json(STATUS_FILE, status)
        result = {"status": "updated", "new_status": args.status}
    else:
        # 完整更新
        stats = json.loads(args.stats) if args.stats else {}
        current_task = {
            "phase": args.phase,
            "round": args.round,
            "description": args.description
        } if args.phase else None
        result = update_status(stats, current_task)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()