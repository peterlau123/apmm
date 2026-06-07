#!/usr/bin/env python3
"""
monitor_agent_daemon.py - 监控 agent.py 守护进程状态并发送飞书通知

功能:
  1. 检查守护进程是否运行 (ping)
  2. 检查端口是否可连接
  3. 检查进程是否存在
  4. 发现异常时发送飞书通知

用法:
  python scripts/monitor_agent_daemon.py [--profile NAME]

返回:
  - 正常: 静默 (无输出)
  - 异常: 输出错误信息 + 发送飞书通知
"""

import os
import sys
import json
import socket
import subprocess
import time
import requests

# 添加项目根目录到路径
PROJECT_ROOT = os.environ.get("APMM_ROOT") or "D:/workspace/apmm"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 从 agent.py 导入配置
try:
    from agent import (
        DAEMON_HOST, DAEMON_PORT, DEFAULT_PROFILE,
        get_profile, daemon_port_for, load_creds, list_profiles
    )
except ImportError as e:
    print(f"[错误] 无法导入 agent.py: {e}")
    sys.exit(1)

# 飞书配置
FEISHU_APP_ID = "cli_aa951cb0dfb9dbda"
FEISHU_APP_SECRET = "rTOni1va857lni9DQKn6Pd1EOPP8nYJ0"
FEISHU_CHAT_ID = "oc_2e75db818ac1792238037a704b4d32d3"


def get_feishu_token():
    """获取飞书 tenant_access_token"""
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    resp = requests.post(url, json={'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET}, timeout=10)
    result = resp.json()
    if result.get('code') == 0:
        return result['tenant_access_token']
    return None


def send_feishu_message(content_text):
    """发送飞书消息"""
    token = get_feishu_token()
    if not token:
        print("[飞书] 无法获取 token，通知发送失败")
        return False
    
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    send_url = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'
    
    data = {
        'receive_id': FEISHU_CHAT_ID,
        'msg_type': 'text',
        'content': json.dumps({'text': content_text})
    }
    
    try:
        resp = requests.post(send_url, headers=headers, json=data, timeout=10)
        result = resp.json()
        if result.get('code') == 0:
            return True
        else:
            print("[飞书] 发送失败:", result.get('msg'))
            return False
    except Exception as e:
        print("[飞书] 发送异常:", e)
        return False


def check_port(port, host="127.0.0.1", timeout=3):
    """检查端口是否可连接"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def ping_daemon(profile):
    """尝试 ping 守护进程"""
    try:
        creds = get_profile(profile)
        daemon_port = daemon_port_for(creds)
        
        req = {"action": "ping"}
        with socket.create_connection((DAEMON_HOST, daemon_port), timeout=5) as s:
            s.sendall((json.dumps(req) + "\n").encode())
            s.settimeout(5)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            resp = json.loads(buf.split(b"\n")[0].decode())
            return resp.get("status") == "ok"
    except Exception:
        return False


def check_process_running(port):
    """检查是否有进程监听指定端口"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if "127.0.0.1:" + str(port) in line or "0.0.0.0:" + str(port) in line:
                if "LISTENING" in line:
                    return True
        return False
    except Exception:
        return None


def monitor_all_profiles():
    """监控所有配置的 profile"""
    profiles = list_profiles()
    
    if not profiles:
        return "[警告] 没有配置任何 profile"
    
    errors = []
    
    # 只监控指定的 profile
    MONITOR_PROFILES = ["t_ascend", "t_h20"]
    
    for name, creds in sorted(profiles.items()):
        if name not in MONITOR_PROFILES:
            continue
        
        port = daemon_port_for(creds)
        
        # 1. 检查端口
        port_ok = check_port(port)
        if not port_ok:
            errors.append("[错误] profile '" + name + "' 端口 " + str(port) + " 无法连接 - 守护进程可能未运行")
            continue
        
        # 2. Ping daemon
        ping_ok = ping_daemon(name)
        if not ping_ok:
            errors.append("[错误] profile '" + name + "' ping 失败 - SSH 会话可能已断开")
            continue
        
        # 3. 检查进程
        proc_ok = check_process_running(port)
        if proc_ok is False:
            errors.append("[错误] profile '" + name + "' 无进程监听端口 " + str(port))
            continue
    
    if errors:
        error_msg = "\n".join(errors)
        # 发送飞书通知
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        feishu_content = "[Hermes 监控告警]\n\n时间: " + timestamp + "\n\n检测到以下异常:\n\n" + error_msg + "\n\n请检查 SSH 堡垒机守护进程状态。"
        send_feishu_message(feishu_content)
        return error_msg
    
    # 全部正常 - 静默
    return ""


def main():
    result = monitor_all_profiles()
    
    if result:
        print(result)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()