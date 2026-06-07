"""
Environment 消息发送脚本
写入.agents/environment/messages.jsonl
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent / ".agents"
MESSAGES_FILE = AGENTS_DIR / "environment" / "messages.jsonl"

def send_message(msg_type: str, priority: str, data: dict):
    """发送消息给Supervisor"""
    
    message = {
        "type": msg_type,
        "priority": priority,
        "timestamp": datetime.now().isoformat(),
        "agent_id": "environment",
        "data": data
    }
    
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MESSAGES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    
    return {"sent": True, "type": msg_type, "priority": priority}

def main():
    parser = argparse.ArgumentParser(description="消息发送")
    parser.add_argument("--type", required=True, help="消息类型")
    parser.add_argument("--priority", default="P2", help="优先级")
    parser.add_argument("--data", type=str, help="数据JSON")
    
    args = parser.parse_args()
    
    data = json.loads(args.data) if args.data else {}
    result = send_message(args.type, args.priority, data)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()