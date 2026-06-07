"""
Runner后台循环脚本
职责：监控存活、处理inbox、更新心跳、检测停滞
"""

import json
import time
import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# 配置 - 使用绝对路径
AGENTS_DIR = Path("D:/workspace/apmm/.agents")
HEARTBEAT_FILE = AGENTS_DIR / "unit-test-runner" / "heartbeat.json"
STATUS_FILE = AGENTS_DIR / "unit-test-runner" / "status.json"
INBOX_FILE = AGENTS_DIR / "unit-test-runner" / "inbox.jsonl"
MESSAGES_FILE = AGENTS_DIR / "unit-test-runner" / "messages.jsonl"
LOCK_FILE = AGENTS_DIR / "unit-test-runner" / "loop.lock"
PROCESSED_FILE = AGENTS_DIR / "unit-test-runner" / "processed_inbox.jsonl"

# 频率配置
INTERVAL = 5  # 主循环间隔（秒）
CLI_TIMEOUT = 30  # CLI停滞阈值（秒）
INSTANCE_TIMEOUT = 30  # 单实例检测阈值（秒）

def write_json(file_path, data):
    """写入JSON文件"""
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def read_json(file_path):
    """读取JSON文件"""
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def parse_time(time_str):
    """解析时间字符串"""
    try:
        # 处理带时区和不带时区的时间
        if '+' in time_str or time_str.endswith('Z'):
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(time_str)
    except:
        return datetime.now(timezone.utc)

def update_heartbeat():
    """更新心跳（证明后台进程存活）"""
    write_json(HEARTBEAT_FILE, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "runner_loop",
        "pid": os.getpid()
    })

def check_single_instance():
    """单实例检测"""
    if LOCK_FILE.exists():
        lock = read_json(LOCK_FILE)
        lock_time = lock.get("timestamp")
        
        if lock_time:
            elapsed = (datetime.now(timezone.utc) - parse_time(lock_time)).total_seconds()
            if elapsed < INSTANCE_TIMEOUT:
                # 检查进程是否真的存活
                pid = lock.get("pid")
                if pid and is_process_alive(pid):
                    print(f"[INFO] Another instance running (PID: {pid}, heartbeat: {elapsed:.1f}s ago)")
                    sys.exit(0)
    
    # 写入锁文件
    write_json(LOCK_FILE, {
        "pid": os.getpid(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

def is_process_alive(pid):
    """检查进程是否存活"""
    try:
        # Windows: 使用tasklist
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
            encoding='gbk'  # Windows中文环境使用GBK编码
        )
        return str(pid) in result.stdout
    except:
        # 无法检查时假设存活
        return True

def check_cli_alive():
    """检查Claude Code CLI存活"""
    heartbeat = read_json(HEARTBEAT_FILE)
    last_time = heartbeat.get("timestamp")
    source = heartbeat.get("source")
    
    if last_time and source == "claude_code":
        elapsed = (datetime.now(timezone.utc) - parse_time(last_time)).total_seconds()
        
        if elapsed > CLI_TIMEOUT:
            # CLI停滞，发送消息
            send_message("runner_stalled", "P0", {
                "last_heartbeat": last_time,
                "elapsed_seconds": elapsed,
                "source": source
            })
            
            # 更新状态为stalled
            status = read_json(STATUS_FILE)
            status["status"] = "stalled"
            status["stalled_at"] = datetime.now(timezone.utc).isoformat()
            write_json(STATUS_FILE, status)
            
            print(f"[WARN] CLI stalled: {elapsed:.1f}s since last heartbeat")

def check_inbox():
    """检查inbox指令"""
    if not INBOX_FILE.exists():
        return
    
    # 读取已处理的消息ID
    processed_ids = set()
    if PROCESSED_FILE.exists():
        for line in PROCESSED_FILE.read_text(encoding="utf-8").strip().split('\n'):
            if line:
                try:
                    msg = json.loads(line)
                    processed_ids.add(msg.get("id", ""))
                except:
                    pass
    
    # 处理新消息
    new_processed = []
    for line in INBOX_FILE.read_text(encoding="utf-8").strip().split('\n'):
        if not line:
            continue
        try:
            msg = json.loads(line)
            msg_id = msg.get("id", msg.get("timestamp", ""))
            
            if msg_id not in processed_ids:
                handle_inbox_message(msg)
                new_processed.append(msg)
        except json.JSONDecodeError:
            continue
    
    # 写入已处理记录
    if new_processed:
        with open(PROCESSED_FILE, 'a', encoding="utf-8") as f:
            for msg in new_processed:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')

def handle_inbox_message(msg):
    """处理单条inbox消息"""
    msg_type = msg.get("type")
    
    if msg_type == "pause":
        handle_pause()
    elif msg_type == "resume":
        handle_resume()
    elif msg_type == "stop":
        handle_stop()
    elif msg_type == "status_request":
        handle_status_request(msg)
    elif msg_type == "start_test":
        handle_start_test(msg)

def handle_pause():
    """处理pause指令"""
    status = read_json(STATUS_FILE)
    status["status"] = "paused"
    status["paused_at"] = datetime.now(timezone.utc).isoformat()
    write_json(STATUS_FILE, status)
    print("[INFO] Paused by Supervisor")
    
    # 发送确认消息
    send_message("runner_paused", "P2", {"timestamp": datetime.now(timezone.utc).isoformat()})

def handle_resume():
    """处理resume指令"""
    status = read_json(STATUS_FILE)
    status["status"] = "running"
    status["resumed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(STATUS_FILE, status)
    print("[INFO] Resumed by Supervisor")
    
    # 发送确认消息
    send_message("runner_resumed", "P2", {"timestamp": datetime.now(timezone.utc).isoformat()})

def handle_stop():
    """处理stop指令"""
    print("[INFO] Stop received, cleaning up...")
    
    # 更新状态
    status = read_json(STATUS_FILE)
    status["status"] = "stopped"
    status["stopped_at"] = datetime.now(timezone.utc).isoformat()
    write_json(STATUS_FILE, status)
    
    # 清理锁文件
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()
    
    # 发送退出消息
    send_message("runner_stopped", "P2", {"timestamp": datetime.now(timezone.utc).isoformat()})
    
    sys.exit(0)

def handle_status_request(msg):
    """处理status_request指令"""
    status = read_json(STATUS_FILE)
    heartbeat = read_json(HEARTBEAT_FILE)
    
    send_message("runner_status_response", "P2", {
        "status": status.get("status", "unknown"),
        "progress": status.get("progress", {}),
        "last_heartbeat": heartbeat.get("timestamp"),
        "loop_pid": os.getpid()
    })

def handle_start_test(msg):
    """处理start_test指令"""
    status = read_json(STATUS_FILE)
    status["status"] = "starting_test"
    status["phase"] = msg.get("data", {}).get("phase", 1)
    status["total_tests"] = msg.get("data", {}).get("total_tests", 0)
    write_json(STATUS_FILE, status)
    print(f"[INFO] Start test command received: Phase {status['phase']}")

def send_message(msg_type, priority, data):
    """发送消息到messages.jsonl"""
    msg = {
        "type": msg_type,
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "unit-test-runner",
        "source": "runner_loop",
        "data": data
    }
    
    with open(MESSAGES_FILE, 'a', encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')

# === 新增：status变化检测 ===
LAST_STATUS = None  # 记录上次status状态

def detect_status_changes(old, new):
    """检测关键字段变化"""
    changes = []
    
    # 检测进度变化
    old_progress = old.get("progress", {})
    new_progress = new.get("progress", {})
    
    if old_progress.get("completed_tests") != new_progress.get("completed_tests"):
        changes.append(f"completed_tests: {old_progress.get('completed_tests')} → {new_progress.get('completed_tests')}")
    
    if old_progress.get("passed_tests") != new_progress.get("passed_tests"):
        changes.append(f"passed_tests: {old_progress.get('passed_tests')} → {new_progress.get('passed_tests')}")
    
    if old_progress.get("failed_tests") != new_progress.get("failed_tests"):
        changes.append(f"failed_tests: {old_progress.get('failed_tests')} → {new_progress.get('failed_tests')}")
    
    # 检测状态变化
    if old.get("status") != new.get("status"):
        changes.append(f"status: {old.get('status')} → {new.get('status')}")
    
    # 检测批次变化
    if old.get("current_batch") != new.get("current_batch"):
        changes.append(f"batch: {old.get('current_batch')} → {new.get('current_batch')}")
    
    # 检测Phase变化
    if old.get("current_phase") != new.get("current_phase"):
        changes.append(f"phase: {old.get('current_phase')} → {new.get('current_phase')}")
    
    # 检测test_status变化
    if old.get("test_status") != new.get("test_status"):
        changes.append(f"test_status: {old.get('test_status')} → {new.get('test_status')}")
    
    return changes

def check_status_change():
    """检测status.json变化并发送消息"""
    global LAST_STATUS
    
    current_status = read_json(STATUS_FILE)
    
    if LAST_STATUS is None:
        LAST_STATUS = current_status
        return
    
    # 检测变化
    changes = detect_status_changes(LAST_STATUS, current_status)
    
    if changes:
        # 发送status_update消息
        send_message("status_update", "P2", {
            "status": current_status.get("status"),
            "progress": current_status.get("progress"),
            "test_status": current_status.get("test_status"),
            "current_phase": current_status.get("current_phase"),
            "current_batch": current_status.get("current_batch"),
            "changes": changes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        LAST_STATUS = current_status
        print(f"[INFO] Status changed: {changes}")
    else:
        # 无变化，更新LAST_STATUS时间戳（保持最新）
        LAST_STATUS = current_status

def main_loop():
    """主循环"""
    print(f"[INFO] Runner loop started (PID: {os.getpid()})")
    
    # 单实例检测
    check_single_instance()
    
    # 初始心跳
    update_heartbeat()
    
    # 发送启动消息
    send_message("runner_loop_started", "P2", {"pid": os.getpid()})
    
    loop_count = 0
    while True:
        try:
            loop_count += 1
            
            # 检查inbox
            check_inbox()
            
            # 检测status变化（新增）
            check_status_change()
            
            # 检查CLI存活（每2轮=10秒）
            if loop_count % 2 == 0:
                check_cli_alive()
            
            # 更新心跳
            update_heartbeat()
            
            # 简要日志（每10轮=50秒）
            if loop_count % 10 == 0:
                print(f"[INFO] Loop running: {loop_count} iterations")
            
            time.sleep(INTERVAL)
            
        except KeyboardInterrupt:
            print("[INFO] Interrupted by user")
            handle_stop()
        except Exception as e:
            print(f"[ERROR] Loop exception: {e}")
            send_message("runner_loop_error", "P1", {"error": str(e)})
            time.sleep(INTERVAL)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=5, help="Loop interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    
    INTERVAL = args.interval
    
    if args.once:
        check_inbox()
        check_cli_alive()
        update_heartbeat()
        print("[INFO] Single check completed")
    else:
        main_loop()