"""
Runner消息发送脚本
写入.agents/runner/messages.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
MESSAGES_FILE = AGENTS_DIR / "unit-test-runner" / "messages.jsonl"

def send_message(msg_type: str, priority: str, data: dict, request_id: str = None):
    """
    发送消息给Supervisor
    
    Args:
        msg_type: bastion_disconnect, gpu_occupied, progress_milestone等
        priority: P0, P1, P2
        data: 消息数据
        request_id: 可选的请求ID
    """
    message = {
        "type": msg_type,
        "priority": priority,
        "timestamp": datetime.now().isoformat(),
        "agent_id": "unit-test-runner",
        "data": data
    }
    
    if request_id:
        message["request_id"] = request_id
    
    # 写入消息队列
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MESSAGES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    
    return {
        "sent": True,
        "type": msg_type,
        "priority": priority,
        "timestamp": message["timestamp"]
    }

def main():
    parser = argparse.ArgumentParser(description="Runner消息发送脚本")
    parser.add_argument("--type", required=True, help="消息类型")
    parser.add_argument("--priority", default="P2", help="优先级 P0/P1/P2")
    parser.add_argument("--data", type=str, help="JSON数据字符串")
    parser.add_argument("--request-id", type=str, default=None, help="请求ID")
    
    args = parser.parse_args()
    
    data = json.loads(args.data) if args.data else {}
    result = send_message(args.type, args.priority, data, args.request_id)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()