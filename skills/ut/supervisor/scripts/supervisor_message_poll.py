"""
Supervisor消息轮询脚本
频率: 每10秒执行
功能: 读取各Agent消息队列，路由转发，发送飞书通知
"""

import json
from pathlib import Path
from datetime import datetime
import sys

# 配置 - 使用绝对路径
AGENTS_DIR = Path("D:/workspace/apmm/.agents")
MESSAGE_QUEUES = [
    AGENTS_DIR / "unit-test-runner" / "messages.jsonl",
    AGENTS_DIR / "environment" / "messages.jsonl",
    AGENTS_DIR / "bastion" / "messages.jsonl",
]
GLOBAL_STATE_FILE = AGENTS_DIR / "global_state.json"
HEARTBEAT_FILE = AGENTS_DIR / "supervisor" / "heartbeat.json"
ARCHIVE_FILE = AGENTS_DIR / "archive" / "processed_messages.jsonl"
PROCESSED_TIME_FILE = AGENTS_DIR / "archive" / "last_poll_time.json"

# 消息路由规则
MESSAGE_ROUTER = {
    # Runner消息
    "bastion_disconnect": {
        "route": ["bastion"],
        "action": "check_and_reconnect",
        "feishu": {"type": "alert", "template": "bastion_disconnect"}
    },
    "dependency_request": {
        "route": ["environment", "runner"],
        "actions": ["download_dependency", "download_started"],
        "feishu": {"type": "info", "template": "dependency_request"}
    },
    "gpu_occupied": {
        "route": ["environment", "runner"],
        "actions": ["check_gpu", "use_idle_gpus"],
        "feishu": {"type": "alert", "template": "gpu_occupied"}
    },
    "progress_milestone": {
        "route": [],
        "feishu": {"type": "progress", "template": "milestone"}
    },
    "phase_complete": {
        "route": [],
        "feishu": {"type": "success", "template": "phase_complete"}
    },
    "all_complete": {
        "route": [],
        "feishu": {"type": "success", "template": "all_complete"}
    },
    "agent_started": {
        "route": [],
        "feishu": {"type": "info", "template": "agent_started"}
    },
    "fallback_triggered": {
        "route": [],
        "feishu": {"type": "warning", "template": "fallback_triggered"}
    },
    # Environment消息
    "gpu_intrusion": {
        "route": [],
        "feishu": {"type": "alert", "template": "gpu_intrusion", "need_human": True}
    },
    "cpu_intrusion": {
        "route": [],
        "feishu": {"type": "alert", "template": "cpu_intrusion"}
    },
    "container_error": {
        "route": [],
        "feishu": {"type": "alert", "template": "container_error", "need_human": True}
    },
    "dependency_ready": {
        "route": ["runner"],
        "action": "resume_tests",
        "feishu": {"type": "info", "template": "dependency_ready"}
    },
    "dependency_failed": {
        "route": ["runner"],
        "action": "skip_dependency",
        "feishu": {"type": "alert", "template": "dependency_failed", "need_human": True}
    },
    "environment_status": {
        "route": [],
        "feishu": None
    },
    # Bastion消息
    "bastion_unstable": {
        "route": [],
        "feishu": {"type": "warning", "template": "bastion_unstable"}
    },
    "otp_required": {
        "route": [],
        "feishu": {"type": "alert", "template": "otp_required", "need_human": True}
    },
    "otp_expired": {
        "route": [],
        "feishu": {"type": "warning", "template": "otp_expired", "need_human": True}
    },
    "bastion_recovered": {
        "route": ["runner"],
        "action": "resume_execution",
        "feishu": {"type": "info", "template": "bastion_recovered"}
    },
    "bastion_recovery_failed": {
        "route": [],
        "feishu": {"type": "alert", "template": "bastion_recovery_failed", "need_human": True}
    },
    "bastion_status": {
        "route": [],
        "feishu": None
    },
}

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def write_json(file_path, data):
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def read_new_messages(queue_file, since_time):
    """读取指定时间之后的新消息"""
    messages = []
    try:
        content = Path(queue_file).read_text(encoding="utf-8").strip()
        if not content:
            return messages
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    msg_time = msg.get("timestamp")
                    if msg_time:
                        # 比较时间戳 - 处理timezone
                        msg_dt = datetime.fromisoformat(msg_time)
                        since_dt = datetime.fromisoformat(since_time)
                        # 确保都是naive datetime
                        if msg_dt.tzinfo:
                            msg_dt = msg_dt.replace(tzinfo=None)
                        if since_dt.tzinfo:
                            since_dt = since_dt.replace(tzinfo=None)
                        if msg_dt > since_dt:
                            messages.append(msg)
                except json.JSONDecodeError as e:
                    print(f"[WARN] JSON parse error in {queue_file}: {e}")
                    continue
    except FileNotFoundError:
        pass
    return messages

def write_to_inbox(agent_id, message):
    """写入指定Agent的inbox"""
    inbox_file = AGENTS_DIR / agent_id / "inbox.jsonl"
    inbox_file.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")

def archive_processed_messages(messages):
    """归档已处理消息"""
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        for msg in messages:
            msg["processed_at"] = datetime.now().isoformat()
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

def update_heartbeat():
    """更新心跳"""
    write_json(HEARTBEAT_FILE, {"timestamp": datetime.now().isoformat()})

def get_last_poll_time():
    """获取上次轮询时间"""
    try:
        data = read_json(PROCESSED_TIME_FILE)
        return data.get("last_poll_time", datetime.now().isoformat())
    except:
        return datetime.now().isoformat()

def save_last_poll_time(time_str):
    """保存本次轮询时间"""
    write_json(PROCESSED_TIME_FILE, {"last_poll_time": time_str})

def priority_order(priority):
    """优先级排序"""
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 2)

def send_feishu_card(feishu_config, msg, original_msg):
    """发送飞书卡片"""
    import requests
    
    # 加载飞书配置
    feishu_config_file = AGENTS_DIR / "feishu_config.json"
    if not feishu_config_file.exists():
        print(f"[ERROR] Feishu config not found")
        return
    
    config = json.loads(feishu_config_file.read_text(encoding="utf-8"))
    
    # 获取token
    BASE_URL = "https://open.feishu.cn/open-apis"
    resp = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": config["app_id"], "app_secret": config["app_secret"]},
        timeout=10
    )
    token_data = resp.json()
    
    if token_data.get("code") != 0:
        print(f"[ERROR] Failed to get token: {token_data}")
        return
    
    token = token_data["tenant_access_token"]
    
    # 构建消息内容
    msg_type = msg.get("type", "unknown")
    msg_data = msg.get("data", {})
    
    text_content = f"【{msg_type}】\n"
    if msg_type == "otp_required":
        text_content += "SSH daemon启动需要OTP验证码\n请执行: python agent.py serve t_h20\npython agent.py serve t_ascend"
    elif msg_type == "bastion_disconnect":
        text_content += f"SSH连接断开: {msg_data.get('targets', {})}\n需要启动daemon"
    else:
        text_content += json.dumps(msg_data, ensure_ascii=False, indent=2)
    
    # 发送消息
    message = {
        "receive_id": config["chat_id"],
        "msg_type": "text",
        "content": json.dumps({"text": text_content})
    }
    
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}"},
        json=message,
        timeout=10
    )
    
    result = resp.json()
    if result.get("code") == 0:
        print(f"[FEISHU] Sent: {msg_type} (message_id: {result.get('data', {}).get('message_id', 'N/A')})")
    else:
        print(f"[ERROR] Failed to send: {result}")

def process_message(msg):
    """处理单条消息"""
    msg_type = msg.get("type")
    router = MESSAGE_ROUTER.get(msg_type)
    
    if not router:
        print(f"[WARN] Unknown message type: {msg_type}")
        return
    
    # 路由转发
    routes = router.get("route", [])
    actions = router.get("actions", [None] * len(routes))
    
    for i, target in enumerate(routes):
        action = actions[i] if i < len(actions) else None
        inbox_msg = {
            "type": "response",
            "request_id": msg.get("request_id"),
            "from": "supervisor",
            "action": action,
            "original_message_type": msg_type,
            "timestamp": datetime.now().isoformat()
        }
        write_to_inbox(target, inbox_msg)
        print(f"[ROUTE] {msg_type} -> {target}: {action}")
    
    # 飞书通知（标记需要发送）
    if router.get("feishu"):
        send_feishu_card(router["feishu"], msg, msg)

def main():
    # 1. 获取上次轮询时间
    last_poll_time = get_last_poll_time()
    
    # 2. 读取各Agent新消息
    all_messages = []
    for queue_file in MESSAGE_QUEUES:
        messages = read_new_messages(queue_file, last_poll_time)
        all_messages.extend(messages)
    
    if not all_messages:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No new messages")
        update_heartbeat()
        save_last_poll_time(datetime.now().isoformat())
        return
    
    # 3. 按优先级排序
    all_messages.sort(key=lambda m: priority_order(m.get("priority", "P2")))
    
    # 4. 处理每条消息
    for msg in all_messages:
        process_message(msg)
    
    # 5. 归档已处理消息
    archive_processed_messages(all_messages)
    
    # 6. 更新心跳
    update_heartbeat()
    
    # 7. 保存本次轮询时间
    save_last_poll_time(datetime.now().isoformat())
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {len(all_messages)} messages")

if __name__ == "__main__":
    main()