#!/usr/bin/env python3
"""start_gateway.py - 启动 Hermes Kanban Gateway"""

import subprocess, sys, time, argparse, yaml, json
from pathlib import Path

def run_cmd(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def check_hermes_version():
    r = run_cmd("hermes version")
    if r.returncode != 0:
        print("ERROR: Hermes not installed")
        return False
    print(f"Hermes version: {r.stdout.strip()}")
    return True

def switch_board(slug):
    r = run_cmd(f"hermes kanban boards switch {slug}")
    if r.returncode != 0:
        print(f"ERROR: Failed to switch board: {slug}")
        return False
    print(f"Switched to board: {slug}")
    return True

def start_gateway(profile):
    cmd = f"nohup hermes profile use {profile} && hermes gateway run > /tmp/gateway_{profile}.log 2>&1 &"
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Started gateway: {profile}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.workflow_yaml).read_text(encoding='utf-8'))
    kanban = config.get("kanban", {})
    if not kanban.get("enabled", False):
        print("INFO: Kanban not enabled, skipping")
        sys.exit(0)

    board = kanban.get("board", {}).get("slug", "apmm-ut")
    profiles = kanban.get("profiles", {})
    targets = [profiles.get("orchestrator", "ut-orchestrator"),
               profiles.get("executor", "ut-executor"),
               profiles.get("fixer", "ut-fixer")]

    if not check_hermes_version(): sys.exit(1)
    if not switch_board(board): sys.exit(1)

    for p in targets:
        start_gateway(p)

    time.sleep(5)
    result = {"status": "started", "board": board, "profiles": targets}
    print(f"JSON_OUTPUT: {json.dumps(result)}")
    sys.exit(0)

if __name__ == "__main__":
    main()