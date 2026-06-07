"""
Supervisor Agent统一循环脚本
实现秒级定时轮询（消息、状态、飞书）
支持单实例检测，避免多实例冲突
"""

import json
import time
from pathlib import Path
from datetime import datetime
import threading
import sys

# 配置
AGENTS_DIR = Path(__file__).parent.parent.parent / ".agents"
HEARTBEAT_FILE = AGENTS_DIR / "supervisor" / "heartbeat.json"
STATUS_FILE = AGENTS_DIR / "supervisor" / "status.json"
LOCK_FILE = AGENTS_DIR / "supervisor" / "loop.lock"

# 轮询间隔（秒）
INTERVALS = {
    "message_poll": 10,
    "status_check": 5,
    "status_poll": 30,  # 新增：status.json轮询（兜底）
    "feishu_listen": 60,
}

# === 新增：status轮询相关 ===
LAST_AGENT_STATUS = {}  # 记录各Agent上次status

def poll_agent_status_files():
    """轮询各Agent status.json（兜底机制）"""
    agents = ["bastion", "unit-test-runner", "environment"]
    
    for agent in agents:
        status_file = AGENTS_DIR / agent / "status.json"
        if not status_file.exists():
            continue
        
        current_status = read_json(status_file)
        last_status = LAST_AGENT_STATUS.get(agent)
        
        if last_status is None:
            LAST_AGENT_STATUS[agent] = current_status
            continue
        
        # 检测变化
        changes = detect_agent_status_changes(agent, last_status, current_status)
        
        if changes:
            # 处理变化
            handle_agent_status_change(agent, current_status, changes)
            
            # 更新记录
            LAST_AGENT_STATUS[agent] = current_status
            print(f"[INFO] {agent} status changed (poll): {changes}")

def detect_agent_status_changes(agent, old, new):
    """检测Agent状态变化"""
    changes = []
    
    # Runner: 检测进度变化
    if agent == "unit-test-runner":
        old_progress = old.get("progress", {})
        new_progress = new.get("progress", {})
        
        if old_progress.get("completed_tests") != new_progress.get("completed_tests"):
            changes.append(f"completed: {old_progress.get('completed_tests')} → {new_progress.get('completed_tests')}")
        
        if old.get("status") != new.get("status"):
            changes.append(f"status: {old.get('status')} → {new.get('status')}")
        
        if old.get("test_status") != new.get("test_status"):
            changes.append(f"test_status: {old.get('test_status')} → {new.get('test_status')}")
    
    # Environment: 检测GPU/容器健康
    if agent == "environment":
        old_gpu = old.get("gpu_status", {}).get("healthy")
        new_gpu = new.get("gpu_status", {}).get("healthy")
        
        if old_gpu != new_gpu:
            changes.append(f"GPU: {old_gpu} → {new_gpu}")
        
        old_container = old.get("container_status", {}).get("healthy")
        new_container = new.get("container_status", {}).get("healthy")
        
        if old_container != new_container:
            changes.append(f"Container: {old_container} → {new_container}")
    
    # Bastion: 检测连接状态
    if agent == "bastion":
        old_conn = old.get("bastion_status", {})
        new_conn = new.get("bastion_status", {})
        
        if old_conn.get("t_h20") != new_conn.get("t_h20"):
            changes.append(f"t_h20: {old_conn.get('t_h20')} → {new_conn.get('t_h20')}")
        
        if old_conn.get("t_ascend") != new_conn.get("t_ascend"):
            changes.append(f"t_ascend: {old_conn.get('t_ascend')} → {new_conn.get('t_ascend')}")
    
    return changes

def handle_agent_status_change(agent, status, changes):
    """处理Agent状态变化（飞书通知）"""
    # 简化版：直接打印日志，详细飞书通知由message_poll处理
    for change in changes:
        print(f"[POLL] {agent}: {change}")
    
    # 可以扩展：发送飞书通知
    # send_feishu_notification(agent, changes)

# 单实例检测阈值（秒）
INSTANCE_TIMEOUT = 30  # 如果心跳超过30秒未更新，认为实例已死

def write_json(file_path, data):
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def update_heartbeat():
    write_json(HEARTBEAT_FILE, {"timestamp": datetime.now().isoformat()})

def update_status(status_text):
    write_json(STATUS_FILE, {
        "agent_id": "supervisor",
        "agent_type": "hermes",
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "last_update": datetime.now().isoformat(),
        "current_task": {"description": status_text}
    })

def run_message_poll():
    """执行消息轮询"""
    import subprocess
    import sys
    try:
        # 使用subprocess调用脚本，避免import路径问题
        script_path = Path(__file__).parent / "supervisor_message_poll.py"
        subprocess.run([sys.executable, str(script_path)], check=False)
    except Exception as e:
        print(f"[ERROR] message_poll: {e}")

def run_status_check():
    """执行状态检查"""
    import subprocess
    import sys
    try:
        script_path = Path(__file__).parent / "supervisor_status_check.py"
        subprocess.run([sys.executable, str(script_path)], check=False)
    except Exception as e:
        print(f"[ERROR] status_check: {e}")

def run_feishu_listen():
    """执行飞书监听"""
    import subprocess
    import sys
    try:
        script_path = Path(__file__).parent / "supervisor_feishu_listen.py"
        subprocess.run([sys.executable, str(script_path)], check=False)
    except Exception as e:
        print(f"[ERROR] feishu_listen: {e}")

def check_existing_instance():
    """检查是否有其他实例在运行"""
    try:
        lock_data = read_json(LOCK_FILE)
        if lock_data:
            pid = lock_data.get("pid")
            start_time = lock_data.get("start_time")
            
            # 检查心跳是否活跃
            heartbeat = read_json(HEARTBEAT_FILE)
            if heartbeat.get("timestamp"):
                heartbeat_time = datetime.fromisoformat(heartbeat["timestamp"])
                elapsed = (datetime.now() - heartbeat_time).total_seconds()
                
                if elapsed < INSTANCE_TIMEOUT:
                    print(f"[INFO] Another instance is running (PID: {pid}, heartbeat: {elapsed}s ago)")
                    return True
            
            # 心跳过期，可以接管
            print(f"[INFO] Previous instance appears dead (heartbeat: {elapsed}s ago), taking over")
    except Exception as e:
        print(f"[INFO] No existing instance detected")
    
    return False

def acquire_lock():
    """获取运行锁"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(LOCK_FILE, {
        "pid": "supervisor_loop",
        "start_time": datetime.now().isoformat()
    })

def release_lock():
    """释放运行锁"""
    try:
        LOCK_FILE.unlink()
    except:
        pass

def supervisor_loop():
    """主循环"""
    # 单实例检测
    if check_existing_instance():
        print("[EXIT] Another instance is running, exiting...")
        return
    
    # 获取锁
    acquire_lock()
    
    print("=" * 60)
    print("Supervisor Agent Loop Started")
    print("=" * 60)
    print(f"Message poll interval: {INTERVALS['message_poll']}s")
    print(f"Status check interval: {INTERVALS['status_check']}s")
    print(f"Feishu listen interval: {INTERVALS['feishu_listen']}s")
    print("=" * 60)
    
    update_status("Supervisor loop started")
    
    counters = {
        "message_poll": 0,
        "status_check": 0,
        "status_poll": 0,  # 新增
        "feishu_listen": 0,
    }
    
    try:
        while True:
            now = time.time()
            
            # 消息轮询（10秒）
            if counters["message_poll"] >= INTERVALS["message_poll"]:
                run_message_poll()
                counters["message_poll"] = 0
            
            # 状态检查（30秒）
            if counters["status_check"] >= INTERVALS["status_check"]:
                run_status_check()
                counters["status_check"] = 0
            
            # status.json轮询（30秒，兜底）
            if counters["status_poll"] >= INTERVALS["status_poll"]:
                poll_agent_status_files()
                counters["status_poll"] = 0
            
            # 飞书监听（60秒）
            if counters["feishu_listen"] >= INTERVALS["feishu_listen"]:
                run_feishu_listen()
                counters["feishu_listen"] = 0
            
            # 更新心跳
            update_heartbeat()
            
            # 等待1秒
            time.sleep(1)
            
            # 增加计数器
            counters["message_poll"] += 1
            counters["status_check"] += 1
            counters["status_poll"] += 1  # 新增
            counters["feishu_listen"] += 1
            
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Supervisor loop stopped by user")
        update_status("Stopped by user")
        release_lock()
    except Exception as e:
        print(f"\n[ERROR] Supervisor loop crashed: {e}")
        update_status(f"Error: {e}")
        release_lock()

def main():
    supervisor_loop()

if __name__ == "__main__":
    main()