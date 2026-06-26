#!/usr/bin/env python3
"""start_ut_workflow.py - UT Workflow一键启动脚本"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

def deploy_tier(tier: str):
    cmd = [sys.executable, str(REPO_ROOT / "tasks/ut/scripts/deploy_tier.py"), "--tier", tier]
    subprocess.run(cmd, check=True)
    print(f"[✓] Tier {tier} profiles deployed")

def start_gateway(mode: str, workflow_yaml: Path):
    if mode == "kanban":
        cmd = [sys.executable, str(REPO_ROOT / "skills/ut/hermes_workflow/scripts/start_gateway.py"), "--workflow-yaml", str(workflow_yaml)]
        subprocess.run(cmd, check=True)
        print(f"[✓] Gateway started for {mode} mode")
    elif mode == "linear":
        cmd = [sys.executable, str(REPO_ROOT / "skills/ut/terminal-workflow/scripts/run_workflow.py"), "--workflow-yaml", str(workflow_yaml)]
        subprocess.Popen(cmd)
        print(f"[✓] Linear workflow started")

def create_kanban_task(workflow_yaml: Path):
    import json
    workflow_config = json.loads(workflow_yaml.read_text(encoding='utf-8'))
    tier = workflow_config.get('tier', 'L4')
    cmd = ["hermes", "kanban", "create", f"UT Workflow: {tier} run", "--assignee", "ut-orchestrator", "--priority", "1"]
    subprocess.run(cmd, check=True)
    print(f"[✓] Kanban task created")

def check_gateway_status():
    cmd = ["hermes", "gateway", "status"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[✓] Gateway status: {result.stdout}")
        return True
    else:
        print(f"[✗] Gateway not running: {result.stderr}")
        return False

def main():
    parser = argparse.ArgumentParser(description="UT Workflow一键启动")
    parser.add_argument("--tier", required=True, choices=["L1", "L2", "L3", "L4"])
    parser.add_argument("--mode", required=True, choices=["linear", "kanban"])
    parser.add_argument("--auto-create-task", action="store_true")
    parser.add_argument("--workflow-yaml", type=Path, default=None)
    
    args = parser.parse_args()
    
    if args.workflow_yaml:
        workflow_yaml = args.workflow_yaml
    else:
        workflow_yaml = REPO_ROOT / f"tests/ut/integration/fixtures/workflow.{args.tier.lower()}.yaml"
    
    if not workflow_yaml.exists():
        print(f"[✗] Workflow config not found: {workflow_yaml}")
        sys.exit(1)
    
    print(f"=== Starting UT Workflow ({args.tier}, {args.mode}) ===")
    deploy_tier(args.tier)
    start_gateway(args.mode, workflow_yaml)
    
    if args.mode == "kanban" and args.auto_create_task:
        create_kanban_task(workflow_yaml)
    
    if args.mode == "kanban":
        check_gateway_status()
    
    print(f"=== UT Workflow Started Successfully ===")
    print(f"Monitor: hermes kanban list")

if __name__ == "__main__":
    main()
