#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from feishu_api import FeishuAPI


def run_cmd(args, cwd, timeout):
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def ping_daemon(workspace, profile):
    try:
        result = run_cmd(["python", "tools/agent.py", "-p", profile, "ping"], workspace, 10)
        return result.returncode == 0 and "[OK]" in result.stdout
    except subprocess.TimeoutExpired:
        return False


def send_request(api, profile, reason, task_id, timeout):
    lines = [
        f"**Profile**: `{profile}`",
        f"**Task**: `{task_id or 'N/A'}`",
        f"**Reason**: {reason}",
        "",
        "需要人工确认后才会重启 agent.py daemon。",
        "请在本群回复：`OTP 123456`",
        f"等待超时：{timeout}s",
        "",
        "注意：OTP 只用于本次启动，不会写入文件。",
    ]
    return api.send_card({
        "header": {"title": "UT Workflow 需要重启 agent.py daemon", "template": "red"},
        "content": "\n".join(lines),
    })


def find_otp(api, since_ms):
    pattern = re.compile(r"\bOTP\s+([0-9]{4,8})\b", re.IGNORECASE)
    for msg in api.get_group_messages(limit=50):
        try:
            create_time = int(msg.get("create_time", 0))
        except ValueError:
            create_time = 0
        if create_time < since_ms:
            continue
        match = pattern.search(msg.get("content", ""))
        if match:
            return match.group(1)
    return None


def stop_daemon(workspace, profile):
    try:
        run_cmd(["python", "tools/agent.py", "-p", profile, "stop"], workspace, 20)
    except subprocess.TimeoutExpired:
        pass


def start_daemon(workspace, profile, otp):
    args = ["python", "tools/agent.py", "serve", profile, "--otp", otp]
    kwargs = {
        "cwd": str(workspace),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["preexec_fn"] = os.setpgrp
    subprocess.Popen(args, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="t_h20")
    parser.add_argument("--workspace", default="D:/workspace/apmm")
    parser.add_argument("--feishu-config", default="D:/workspace/apmm/.agents/feishu_config.json")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--force", action="store_true", help="request approval even if ping succeeds")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    if not args.force and ping_daemon(workspace, args.profile):
        print("[OK] daemon already running")
        return 0

    api = FeishuAPI(args.feishu_config)
    since_ms = int(time.time() * 1000)
    if not send_request(api, args.profile, args.reason, args.task_id, args.timeout):
        print("[ERROR] failed to send Feishu approval request")
        return 2

    deadline = time.time() + args.timeout
    otp = None
    while time.time() < deadline:
        otp = find_otp(api, since_ms)
        if otp:
            break
        time.sleep(args.poll_interval)

    if not otp:
        print("[ERROR] OTP approval timeout")
        return 2

    stop_daemon(workspace, args.profile)
    start_daemon(workspace, args.profile, otp)

    for _ in range(30):
        time.sleep(2)
        if ping_daemon(workspace, args.profile):
            print("[OK] daemon restarted")
            return 0

    print("[ERROR] daemon restart did not become healthy")
    return 2


if __name__ == "__main__":
    sys.exit(main())
