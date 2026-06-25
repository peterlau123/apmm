#!/usr/bin/env python3
"""start_gateway.py - 启动 Hermes gateway with embedded Kanban dispatcher"""

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


def gateway_running(profile):
    r = run_cmd(["hermes", "gateway", "list"])
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        if profile in line and "✓" in line:
            return True
    return False


def start_profile_gateway(profile, logs_dir):
    if gateway_running(profile):
        return {"profile": profile, "status": "already_running"}

    use = run_cmd(["hermes", "profile", "use", profile])
    if use.returncode != 0:
        return {"profile": profile, "status": "error", "step": "profile_use", "stderr": use.stderr}

    logs_dir.mkdir(parents=True, exist_ok=True)
    logfile = logs_dir / f"gateway_{profile}.log"
    out = logfile.open("a", encoding="utf-8")

    # Clear PYTHONPATH to prevent Hermes venv environment leak into Gateway workers.
    # Workers inherit Gateway's env and may fail to import jsonschema if PYTHONPATH
    # points to Hermes venv instead of the project's anaconda environment.
    # See incident: tasks/ut/docs/incidents/2026-06-24-pythonpath-leak-incident.md
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)

    kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["preexec_fn"] = os.setpgrp

    proc = subprocess.Popen(["hermes", "gateway", "run"], **kwargs)
    for _ in range(10):
        if gateway_running(profile):
            return {"profile": profile, "status": "started", "pid": proc.pid, "logfile": str(logfile)}
        if proc.poll() is not None:
            break
        time.sleep(1)

    return {"profile": profile, "status": "error", "step": "gateway_run", "pid": proc.pid, "returncode": proc.poll(), "logfile": str(logfile)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    workflow_yaml = Path(args.workflow_yaml)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))
    kanban = config.get("kanban", {})
    if not kanban.get("enabled", False):
        print("INFO: Kanban not enabled, skipping")
        sys.exit(0)

    board = kanban.get("board", {}).get("slug", "apmm-ut")
    profiles = kanban.get("profiles", {})
    targets = [
        profiles.get("orchestrator", "ut-orchestrator"),
        profiles.get("executor", "ut-executor"),
        profiles.get("fixer", "ut-fixer"),
    ]
    workspace = Path(config.get("config", {}).get("workspace", workflow_yaml.parent.parent))
    logs_dir = workspace / ".agents" / "logs"

    if not check_hermes_version():
        sys.exit(1)
    if not switch_board(board):
        sys.exit(1)

    results = [start_profile_gateway(profile, logs_dir) for profile in targets]
    ok = all(result["status"] in {"started", "already_running"} for result in results)
    result = {"status": "started" if ok else "error", "board": board, "profiles": results}
    print(f"JSON_OUTPUT: {json.dumps(result, ensure_ascii=True)}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
