#!/usr/bin/env python3
"""start_supervisor.py - 启动 Hermes Supervisor Agent"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


def run_cmd(cmd, timeout=60):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check_hermes_version():
    r = run_cmd(["hermes", "version"])
    if r.returncode != 0:
        print("ERROR: Hermes not installed")
        print(r.stderr)
        return False
    print(f"Hermes version: {r.stdout.strip()}")
    return True


def switch_board(slug):
    r = run_cmd(["hermes", "kanban", "boards", "switch", slug])
    if r.returncode != 0:
        print(f"ERROR: Failed to switch board: {slug}")
        print(r.stderr)
        return False
    print(f"Switched to board: {slug}")
    return True


def agent_running(profile):
    r = run_cmd(["hermes", "agent", "status"])
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        if profile in line and "running" in line.lower():
            return True
    return False


def start_supervisor_agent(profile, logs_dir, kanban_enabled=True):
    if agent_running(profile):
        return {"profile": profile, "status": "already_running"}

    use = run_cmd(["hermes", "profile", "use", profile])
    if use.returncode != 0:
        return {"profile": profile, "status": "error", "step": "profile_use", "stderr": use.stderr}

    logs_dir.mkdir(parents=True, exist_ok=True)
    logfile = logs_dir / f"supervisor_{profile}.log"
    out = logfile.open("a", encoding="utf-8")
    kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["preexec_fn"] = os.setpgrp

    proc = subprocess.Popen(["hermes", "agent", "run"], **kwargs)
    for _ in range(10):
        if agent_running(profile):
            return {"profile": profile, "status": "started", "pid": proc.pid, "logfile": str(logfile)}
        if proc.poll() is not None:
            break
        time.sleep(1)

    return {"profile": profile, "status": "error", "step": "agent_run", "pid": proc.pid, "returncode": proc.poll(), "logfile": str(logfile)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--start-gateways", action="store_true", default=True, help="Also start 3 Kanban Gateways")
    parser.add_argument("--no-gateways", action="store_true", help="Skip Gateway startup")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    workflow_yaml = Path(args.workflow_yaml)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))
    
    kanban = config.get("kanban", {})
    kanban_enabled = kanban.get("enabled", False)
    board = kanban.get("board", {}).get("slug", "apmm-ut")
    
    bastion = config.get("bastion", {})
    supervisor_profile = bastion.get("profile", "ut-supervisor")
    
    workspace = Path(config.get("config", {}).get("workspace", workflow_yaml.parent.parent))
    logs_dir = workspace / ".agents" / "logs"

    if not check_hermes_version():
        sys.exit(1)

    results = []

    if kanban_enabled and args.start_gateways and not args.no_gateways:
        print("\n=== Starting Kanban Gateways ===")
        if not switch_board(board):
            sys.exit(1)

        profiles = kanban.get("profiles", {})
        gateway_profiles = [
            profiles.get("orchestrator", "ut-orchestrator"),
            profiles.get("executor", "ut-executor"),
            profiles.get("fixer", "ut-fixer"),
        ]

        for profile in gateway_profiles:
            use = run_cmd(["hermes", "profile", "use", profile])
            if use.returncode != 0:
                results.append({"profile": profile, "type": "gateway", "status": "error", "stderr": use.stderr})
                continue

            logfile = logs_dir / f"gateway_{profile}.log"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            out = logfile.open("a", encoding="utf-8")
            kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            else:
                kwargs["preexec_fn"] = os.setpgrp

            proc = subprocess.Popen(["hermes", "gateway", "run"], **kwargs)
            time.sleep(2)
            
            verify = run_cmd(["hermes", "gateway", "list"])
            running = any(profile in line and "✓" in line for line in verify.stdout.splitlines())
            
            if running:
                results.append({"profile": profile, "type": "gateway", "status": "started", "pid": proc.pid, "logfile": str(logfile)})
            else:
                results.append({"profile": profile, "type": "gateway", "status": "error", "pid": proc.pid, "logfile": str(logfile)})

    print("\n=== Starting Supervisor Agent ===")
    supervisor_result = start_supervisor_agent(supervisor_profile, logs_dir, kanban_enabled)
    supervisor_result["type"] = "supervisor"
    results.append(supervisor_result)

    ok = all(result["status"] in {"started", "already_running"} for result in results)
    
    print("\n=== Results ===")
    for r in results:
        print(f"  {r['type']}/{r['profile']}: {r['status']}")
        if r["status"] == "started":
            print(f"    PID: {r.get('pid')}, Log: {r.get('logfile')}")
        elif r["status"] == "error":
            print(f"    Error: {r.get('stderr', r.get('step'))}")

    result_json = {"status": "started" if ok else "error", "board": board, "results": results}
    print(f"\nJSON_OUTPUT: {json.dumps(result_json, ensure_ascii=True)}")
    
    if ok:
        print("\n[OK] All services started. Supervisor is listening to Feishu.")
        print("Send '跑 ut workflow' in Feishu to trigger L4 test.")
    else:
        print("\n[ERROR] Some services failed to start. Check logs in .agents/logs/")
    
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()