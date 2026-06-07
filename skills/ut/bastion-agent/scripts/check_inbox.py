"""
Bastion inbox检查脚本
读取.agents/bastion/inbox.jsonl
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
INBOX_FILE = AGENTS_DIR / "bastion" / "inbox.jsonl"

def read_inbox(limit: int = 20, since_time: str = None):
    """读取inbox消息"""
    
    if not INBOX_FILE.exists():
        return []
    
    messages = []
    content = INBOX_FILE.read_text(encoding="utf-8").strip()
    
    if content:
        lines = content.split("\n")
        for line in lines[-limit:]:
            if line:
                msg = json.loads(line)
                if since_time:
                    if msg.get("timestamp") > since_time:
                        messages.append(msg)
                else:
                    messages.append(msg)
    
    return messages

def main():
    parser = argparse.ArgumentParser(description="inbox检查")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--since", type=str, default=None)
    
    args = parser.parse_args()
    
    messages = read_inbox(args.limit, args.since)
    
    result = {
        "messages": messages,
        "count": len(messages),
        "timestamp": datetime.now().isoformat()
    }
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()