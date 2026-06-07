"""
Runner inbox检查脚本
读取.agents/runner/inbox.jsonl，输出JSON结果
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
INBOX_FILE = AGENTS_DIR / "runner" / "inbox.jsonl"

def read_inbox(limit: int = 20, since_time: str = None):
    """
    读取inbox消息
    
    Args:
        limit: 最大返回条数
        since_time: 只返回此时间后的消息
    
    Returns:
        list: 消息列表
    """
    if not INBOX_FILE.exists():
        return []
    
    messages = []
    try:
        content = INBOX_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return []
        
        lines = content.split("\n")
        for line in lines[-limit:]:
            if line:
                msg = json.loads(line)
                if since_time:
                    msg_time = msg.get("timestamp")
                    if msg_time and msg_time > since_time:
                        messages.append(msg)
                else:
                    messages.append(msg)
    except Exception as e:
        return [{"error": str(e)}]
    
    return messages

def parse_commands(messages: list):
    """解析消息中的指令"""
    commands = []
    for msg in messages:
        msg_type = msg.get("type")
        if msg_type == "command":
            commands.append({
                "action": msg.get("action"),
                "from": msg.get("from"),
                "timestamp": msg.get("timestamp"),
                "original": msg
            })
        elif msg_type == "response":
            commands.append({
                "response_type": msg.get("action"),
                "from": msg.get("from"),
                "timestamp": msg.get("timestamp"),
                "original": msg
            })
    return commands

def main():
    parser = argparse.ArgumentParser(description="Runner inbox检查脚本")
    parser.add_argument("--limit", type=int, default=20, help="最大返回条数")
    parser.add_argument("--since", type=str, default=None, help="只返回此时间后的消息")
    parser.add_argument("--commands", action="store_true", help="仅返回指令消息")
    
    args = parser.parse_args()
    
    messages = read_inbox(args.limit, args.since)
    
    if args.commands:
        result = {
            "commands": parse_commands(messages),
            "count": len(messages),
            "timestamp": datetime.now().isoformat()
        }
    else:
        result = {
            "messages": messages,
            "count": len(messages),
            "timestamp": datetime.now().isoformat()
        }
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()