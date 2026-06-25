"""
Supervisor状态检查脚本
频率: 每30秒执行
功能: 检查Agent状态，检测失联，更新全局状态
"""

import json
from pathlib import Path
from datetime import datetime
import sys

# 配置 - 从脚本目录推断路径
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / ".agents"

# 简化：只监控 Runner（双Agent架构）
AGENT_STATUS_FILES = {
    "unit-test-executor": AGENTS_DIR / "unit-test-executor" / "status.json",
    "supervisor": AGENTS_DIR / "supervisor" / "status.json",
}
GLOBAL_STATE_FILE = AGENTS_DIR / "global_state.json"
LAST_CHECK_FILE = AGENTS_DIR / "archive" / "last_connection_check.json"
DISCONNECT_THRESHOLDS = {
    "level1": 60,   # 可疑
    "level2": 120,  # 确认失联
    "level3": 180,  # 严重失联
}
# connection_check 写入限制：同一 Agent 最多每 5 分钟写入一次
CONNECTION_CHECK_INTERVAL = 300  # 秒

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

def write_to_inbox(agent_id, message):
    """写入指定Agent的inbox"""
    inbox_file = AGENTS_DIR / agent_id / "inbox.jsonl"
    inbox_file.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")

def time_since(timestamp_str):
    """计算时间戳距今秒数"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return (datetime.now() - dt).total_seconds()
    except:
        return 999999  # 无效时间戳视为很久

def check_connection_health(status):
    """检查Agent连接健康状态"""
    last_update = status.get("last_update")
    if not last_update:
        return {"level": "unknown", "seconds": None}
    
    elapsed = time_since(last_update)
    
    if elapsed < DISCONNECT_THRESHOLDS["level1"]:
        return {"level": "healthy", "seconds": elapsed}
    elif elapsed < DISCONNECT_THRESHOLDS["level2"]:
        return {"level": "suspect", "seconds": elapsed}
    elif elapsed < DISCONNECT_THRESHOLDS["level3"]:
        return {"level": "disconnected", "seconds": elapsed}
    else:
        return {"level": "critical", "seconds": elapsed}

def should_write_connection_check(agent_id):
    """检查是否应该写入 connection_check（避免无限写入）"""
    last_checks = read_json(LAST_CHECK_FILE)
    last_time = last_checks.get(agent_id)
    
    if last_time:
        elapsed_since_last_check = time_since(last_time)
        # 限制：同一 Agent 每 5 分钟最多写入一次
        if elapsed_since_last_check < CONNECTION_CHECK_INTERVAL:
            return False
    
    return True

def update_last_check_time(agent_id):
    """更新上次写入 connection_check 的时间"""
    last_checks = read_json(LAST_CHECK_FILE)
    last_checks[agent_id] = datetime.now().isoformat()
    write_json(LAST_CHECK_FILE, last_checks)

def handle_disconnect(agent_id, health):
    """处理Agent失联"""
    level = health["level"]
    elapsed = int(health["seconds"])
    
    print(f"[DISCONNECT] {agent_id}: {level} ({elapsed}s)")
    
    # Level2+ 写入inbox请求确认（限制写入频率）
    if level in ["disconnected", "critical"]:
        if should_write_connection_check(agent_id):
            write_to_inbox(agent_id, {
                "type": "connection_check",
                "request": "please_confirm_status",
                "level": level,
                "elapsed_seconds": elapsed,
                "timestamp": datetime.now().isoformat()
            })
            update_last_check_time(agent_id)
            print(f"[CHECK] connection_check written to {agent_id}")
        else:
            print(f"[SKIP] connection_check skipped for {agent_id} (rate limited)")

def calculate_system_health(global_state):
    """计算系统健康状态"""
    agents = global_state.get("agents", {})
    
    all_connected = all(
        a.get("connection_health") == "healthy" 
        for a in agents.values()
        if a.get("connection_health")
    )
    
    critical_count = sum(
        1 for a in agents.values() 
        if a.get("connection_health") in ["critical", "disconnected"]
    )
    
    bastion_connected = agents.get("bastion", {}).get("connection_health") == "healthy"
    
    return {
        "all_agents_connected": all_connected and len(agents) >= 3,
        "critical_issues": critical_count,
        "bastion_connected": bastion_connected,
        "gpu_available": True,  # 简化处理
    }

def load_global_state():
    """加载全局状态"""
    state = read_json(GLOBAL_STATE_FILE)
    if not state:
        state = {
            "last_update": None,
            "agents": {},
            "test_progress": {},
            "pending_requests": [],
            "recent_alerts": [],
            "system_health": {}
        }
    return state

def save_global_state(state):
    """保存全局状态"""
    state["last_update"] = datetime.now().isoformat()
    write_json(GLOBAL_STATE_FILE, state)

def main():
    global_state = load_global_state()
    
    # 1. 检查各Agent状态
    for agent_id, status_file in AGENT_STATUS_FILES.items():
        status = read_json(status_file)
        health = check_connection_health(status)
        
        # 处理current_task可能是字符串或字典的情况
        current_task_desc = ""
        ct = status.get("current_task")
        if isinstance(ct, dict):
            current_task_desc = ct.get("description", "")
        elif isinstance(ct, str):
            current_task_desc = ct
        
        global_state["agents"][agent_id] = {
            "status": status.get("status", "unknown"),
            "last_update": status.get("last_update"),
            "connection_health": health["level"],
            "current_task": current_task_desc,
        }
        
        # 失联处理
        if health["level"] in ["suspect", "disconnected", "critical"]:
            handle_disconnect(agent_id, health)
            # 记录告警
            global_state["recent_alerts"].append({
                "type": "agent_disconnect",
                "agent_id": agent_id,
                "level": health["level"],
                "timestamp": datetime.now().isoformat()
            })
    
    # 2. 汇总测试进度
    runner_status = read_json(AGENT_STATUS_FILES["unit-test-executor"])
    stats = runner_status.get("statistics", {})
    task = runner_status.get("current_task", {})
    
    global_state["test_progress"] = {
        "phase": task.get("phase"),
        "round": task.get("round"),
        "completed": stats.get("tests_completed", 0),
        "passed": stats.get("tests_passed", 0),
        "failed": stats.get("tests_failed", 0),
        "error": stats.get("tests_error", 0),
        "progress": task.get("progress", ""),
    }
    
    # 3. 计算系统健康状态
    global_state["system_health"] = calculate_system_health(global_state)
    
    # 4. 清理过旧告警（保留最近50条）
    if len(global_state["recent_alerts"]) > 50:
        global_state["recent_alerts"] = global_state["recent_alerts"][-50:]
    
    # 5. 保存全局状态
    save_global_state(global_state)
    
    # 输出状态摘要
    agents_summary = [
        f"{aid}: {info.get('status', '?')} ({info.get('connection_health', '?')})"
        for aid, info in global_state["agents"].items()
    ]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Status check completed")
    print(f"  Agents: {', '.join(agents_summary)}")
    print(f"  Progress: {global_state['test_progress'].get('completed', 0)} tests")

if __name__ == "__main__":
    main()