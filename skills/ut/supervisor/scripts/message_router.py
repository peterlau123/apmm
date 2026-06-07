"""
消息路由辅助函数
提供文件读写、inbox写入、状态管理等功能
"""

import json
from pathlib import Path
from datetime import datetime

AGENTS_DIR = Path(__file__).parent.parent.parent / ".agents"

def read_json(file_path):
    """读取JSON文件"""
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def write_json(file_path, data):
    """写入JSON文件"""
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def read_messages_since(file_path, since_time):
    """读取指定时间之后的消息"""
    messages = []
    try:
        content = Path(file_path).read_text(encoding="utf-8").strip()
        if not content:
            return messages
        lines = content.split("\n")
        for line in lines:
            if line:
                msg = json.loads(line)
                msg_time = msg.get("timestamp")
                if msg_time:
                    msg_dt = datetime.fromisoformat(msg_time)
                    since_dt = datetime.fromisoformat(since_time)
                    if msg_dt > since_dt:
                        messages.append(msg)
    except FileNotFoundError:
        pass
    return messages

def time_since_timestamp(timestamp_str):
    """计算时间戳距今秒数"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return (datetime.now() - dt).total_seconds()
    except:
        return 0

def write_to_inbox(agent_id, message):
    """写入指定Agent的inbox"""
    inbox_file = AGENTS_DIR / agent_id / "inbox.jsonl"
    inbox_file.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")

def load_global_state():
    """加载全局状态"""
    return read_json(AGENTS_DIR / "global_state.json")

def save_global_state(state):
    """保存全局状态"""
    state["last_update"] = datetime.now().isoformat()
    write_json(AGENTS_DIR / "global_state.json", state)

def read_agent_status(status_file):
    """读取Agent状态文件"""
    return read_json(status_file)

def update_heartbeat():
    """更新Supervisor心跳"""
    heartbeat_file = AGENTS_DIR / "supervisor" / "heartbeat.json"
    write_json(heartbeat_file, {"timestamp": datetime.now().isoformat()})

def archive_processed_messages(messages):
    """归档已处理消息"""
    archive_file = AGENTS_DIR / "archive" / "processed_messages.jsonl"
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_file, "a", encoding="utf-8") as f:
        for msg in messages:
            msg["processed_at"] = datetime.now().isoformat()
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

def load_processed_ids():
    """加载已处理的飞书消息ID"""
    file_path = AGENTS_DIR / "archive" / "processed_feishu_ids.json"
    data = read_json(file_path)
    return data.get("ids", [])

def save_processed_ids(ids):
    """保存已处理的飞书消息ID"""
    file_path = AGENTS_DIR / "archive" / "processed_feishu_ids.json"
    write_json(file_path, {"ids": ids[-500:]})

def get_last_processed_time():
    """获取上次处理消息的时间"""
    file_path = AGENTS_DIR / "archive" / "last_poll_time.json"
    data = read_json(file_path)
    return data.get("last_poll_time", datetime.now().isoformat())

def save_last_poll_time(time_str):
    """保存本次轮询时间"""
    file_path = AGENTS_DIR / "archive" / "last_poll_time.json"
    write_json(file_path, {"last_poll_time": time_str})


# 测试
if __name__ == "__main__":
    print("Testing message_router helpers...")
    
    # 测试写入inbox
    write_to_inbox("runner", {
        "type": "test",
        "message": "This is a test message from message_router",
        "timestamp": datetime.now().isoformat()
    })
    print("Test message written to runner inbox")
    
    # 测试心跳更新
    update_heartbeat()
    print("Heartbeat updated")
    
    # 测试全局状态
    state = load_global_state()
    print(f"Global state loaded: {state.get('last_update')}")
    
    print("All tests passed!")