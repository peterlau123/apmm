#!/usr/bin/env python3
"""start_l4_test.py - 启动 L4 测试环境（gateways + supervisor）

前置：先手动启动 Bastion daemon（OTP 无法脚本化）：
    python tools/agent.py serve t_h20      # 输入静态密码 + OTP

启动顺序（本脚本，非交互）：
1. 配置预检（.bastion_creds / workflow.yaml / hermes profiles）
2. 校验 Bastion daemon 已在运行
3. 3 Kanban Gateways (后台)
4. Supervisor Agent (后台)

Usage:
    # 启动 gateways + supervisor（daemon 须已运行）
    python tests/ut/integration/start_l4_test.py

    # 检查配置 + 运行状态
    python tests/ut/integration/start_l4_test.py --status

    # 停止所有服务
    python tests/ut/integration/start_l4_test.py --stop
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

# Windows GBK console can't print box-drawing/check chars; force UTF-8 stdout.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# tests/ut/integration/start_l4_test.py -> project root is three levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_AGENT_PY = _PROJECT_ROOT / "tools" / "agent.py"
_START_GATEWAY_PY = _PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "start_gateway.py"


def run_cmd(cmd, timeout=60, cwd=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check_hermes():
    r = run_cmd(["hermes", "version"])
    if r.returncode != 0:
        print("ERROR: Hermes not installed")
        return False
    print(f"[OK] Hermes: {r.stdout.strip()}")
    return True


def check_bastion_daemon(profile="t_h20"):
    agent_path = _AGENT_PY
    r = run_cmd([sys.executable, str(agent_path), "-p", profile, "ping"])
    if r.returncode == 0 and "[OK]" in r.stdout:
        return True
    return False


def ensure_bastion_daemon(profile="t_h20"):
    """校验 Bastion daemon 已在运行。daemon 须先手动启动（OTP 无法脚本化）。"""
    print("\n" + "="*60)
    print("Step 1: Bastion Daemon (check)")
    print("="*60)

    if check_bastion_daemon(profile):
        print(f"[OK] Bastion daemon running (profile={profile})")
        return True

    print(f"[X] Bastion daemon not running (profile={profile})")
    print("\n先在另一个窗口手动启动 daemon（OTP 无法脚本化）：")
    print(f"  python {_AGENT_PY} serve {profile}")
    print("输入静态密码 + OTP 后，重新运行本脚本。")
    return False


# ── Config preflight (prerequisites, not runtime services) ──────────────────────

def _bastion_creds_present():
    return (_PROJECT_ROOT / ".bastion_creds").exists() or \
        (_PROJECT_ROOT / "tools" / ".bastion_creds").exists()


def _hermes_profiles_present(required):
    r = run_cmd(["hermes", "profile", "list"])
    if r.returncode != 0:
        return {p: False for p in required}
    return {p: (p in r.stdout) for p in required}


def preflight_config(workflow_yaml_path):
    """校验配置前置项（非运行态服务）。返回 ok bool。"""
    print("\n" + "="*60)
    print("Config Preflight")
    print("="*60)

    creds = _bastion_creds_present()
    print(f"  .bastion_creds : {'[OK] present' if creds else '[X] missing — python tools/agent.py setcreds t_h20'}")

    wf = Path(workflow_yaml_path)
    if wf.exists():
        cfg = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
    else:
        print(f"  workflow.yaml  : [X] missing ({workflow_yaml_path})")
        return False

    kanban = cfg.get("kanban", {})
    kanban_on = kanban.get("enabled") is True
    print(f"  kanban.enabled : {'[OK] true' if kanban_on else '[X] not true'}")

    chat_id = cfg.get("notifications", {}).get("feishu_chat_id")
    print(f"  feishu_chat_id : {'[OK] set' if chat_id else '[X] unset'}")

    profiles_cfg = kanban.get("profiles", {})
    required = [
        profiles_cfg.get("orchestrator", "ut-orchestrator"),
        profiles_cfg.get("executor", "ut-executor"),
        profiles_cfg.get("fixer", "ut-fixer"),
        "ut-supervisor",
    ]
    present = _hermes_profiles_present(required)
    for p in required:
        print(f"  profile {p:<16}: {'[OK]' if present[p] else '[X] missing'}")

    ok = creds and kanban_on and bool(chat_id) and all(present.values())
    print(f"\nConfig: {'[OK] READY' if ok else '[X] INCOMPLETE'}")
    return ok


def check_gateway(profile):
    r = run_cmd(["hermes", "gateway", "list"])
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        if profile in line and "✓" in line:
            return True
    return False


def start_gateways(workflow_yaml_path):
    """后台启动 3 Gateway"""
    print("\n" + "="*60)
    print("Step 2: Kanban Gateways")
    print("="*60)
    
    start_gateway_script = _START_GATEWAY_PY
    r = run_cmd([sys.executable, str(start_gateway_script), "--workflow-yaml", workflow_yaml_path])
    
    if r.returncode != 0:
        print(f"[X] Gateway startup failed: {r.stderr}")
        return False
    
    print(f"[OK] Gateways started: {r.stdout.strip()}")
    return True


def check_supervisor(profile="ut-supervisor"):
    r = run_cmd(["hermes", "agent", "status"])
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        if profile in line and "running" in line.lower():
            return True
    return False


def start_supervisor(workflow_yaml_path):
    """后台启动 Supervisor"""
    print("\n" + "="*60)
    print("Step 3: Supervisor Agent")
    print("="*60)
    
    workflow_yaml = Path(workflow_yaml_path)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))
    bastion_profile = config.get("bastion", {}).get("profile", "ut-supervisor")
    
    if check_supervisor(bastion_profile):
        print(f"[OK] Supervisor already running (profile={bastion_profile})")
        return True
    
    print(f"\nStarting Supervisor (profile={bastion_profile})...")
    
    workspace = Path(config.get("config", {}).get("workspace", workflow_yaml.parent.parent))
    logs_dir = workspace / ".agents" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logfile = logs_dir / f"supervisor_{bastion_profile}.log"
    
    use = run_cmd(["hermes", "profile", "use", bastion_profile])
    if use.returncode != 0:
        print(f"[X] Profile use failed: {use.stderr}")
        return False
    
    out = logfile.open("a", encoding="utf-8")
    kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    
    proc = subprocess.Popen(["hermes", "agent", "run"], **kwargs)
    
    for _ in range(10):
        if check_supervisor(bastion_profile):
            print(f"[OK] Supervisor started (PID={proc.pid}, log={logfile})")
            return True
        if proc.poll() is not None:
            break
        time.sleep(1)
    
    print(f"[X] Supervisor failed to start (PID={proc.pid})")
    return False


def show_status(workflow_yaml_path):
    """显示配置预检 + 运行态状态"""
    config_ok = preflight_config(workflow_yaml_path)

    print("\n" + "="*60)
    print("L4 Test Environment Status (runtime)")
    print("="*60)

    workflow_yaml = Path(workflow_yaml_path)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))

    bastion_profile = config.get("bastion", {}).get("profile", "t_h20")
    kanban = config.get("kanban", {})
    profiles = kanban.get("profiles", {})

    gateway_profiles = [
        profiles.get("orchestrator", "ut-orchestrator"),
        profiles.get("executor", "ut-executor"),
        profiles.get("fixer", "ut-fixer"),
    ]
    supervisor_profile = "ut-supervisor"

    print(f"\nBoard: {kanban.get('board', {}).get('slug', 'apmm-ut')}")

    print("\nServices:")

    bastion_ok = check_bastion_daemon(bastion_profile)
    print(f"  Bastion ({bastion_profile}): {'[OK] running' if bastion_ok else '[X] not running'}")

    for profile in gateway_profiles:
        ok = check_gateway(profile)
        print(f"  Gateway ({profile}): {'[OK] running' if ok else '[X] not running'}")

    supervisor_ok = check_supervisor(supervisor_profile)
    print(f"  Supervisor ({supervisor_profile}): {'[OK] running' if supervisor_ok else '[X] not running'}")

    runtime_ok = bastion_ok and all(check_gateway(p) for p in gateway_profiles) and supervisor_ok
    all_ok = config_ok and runtime_ok

    print(f"\nOverall: {'[OK] READY' if all_ok else '[X] NOT READY'}")

    if all_ok:
        print("\nNext: Send '跑 ut workflow' in Feishu to trigger L4 test.")
    elif not config_ok:
        print("\nAction: 先补齐上面标 [X] 的配置项。")
    else:
        print("\nAction: 先手动起 daemon，再运行 'python tests/ut/integration/start_l4_test.py'。")

    return all_ok


def stop_all(workflow_yaml_path):
    """停止所有服务"""
    print("\n" + "="*60)
    print("Stopping L4 Test Environment")
    print("="*60)
    
    workflow_yaml = Path(workflow_yaml_path)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))
    
    bastion_profile = config.get("bastion", {}).get("profile", "t_h20")
    kanban = config.get("kanban", {})
    profiles = kanban.get("profiles", {})
    
    gateway_profiles = [
        profiles.get("orchestrator", "ut-orchestrator"),
        profiles.get("executor", "ut-executor"),
        profiles.get("fixer", "ut-fixer"),
    ]
    supervisor_profile = "ut-supervisor"
    
    agent_path = _AGENT_PY
    
    print(f"\nStopping Bastion daemon ({bastion_profile})...")
    r = run_cmd([sys.executable, str(agent_path), "-p", bastion_profile, "stop"])
    print(f"  {r.stdout.strip()}")
    
    for profile in gateway_profiles:
        print(f"\nStopping Gateway ({profile})...")
        r = run_cmd(["hermes", "gateway", "stop", profile])
        print(f"  {r.stdout.strip() if r.returncode == 0 else r.stderr.strip()}")
    
    print(f"\nStopping Supervisor ({supervisor_profile})...")
    r = run_cmd(["hermes", "agent", "stop", supervisor_profile])
    print(f"  {r.stdout.strip() if r.returncode == 0 else r.stderr.strip()}")
    
    print("\n[OK] All services stopped")


def main():
    parser = argparse.ArgumentParser(description="L4 测试环境启动脚本（daemon 须先手动启动）")
    parser.add_argument(
        "--workflow-yaml",
        default="D:/workspace/apmm/tests/ut/integration/fixtures/workflow.l4.yaml",
        help="L4 frozen config (default). Pass .agents/workflow.yaml to use the live prod config.",
    )
    parser.add_argument("--status", action="store_true", help="Show status only")
    parser.add_argument("--stop", action="store_true", help="Stop all services")
    args = parser.parse_args()
    
    if args.stop:
        stop_all(args.workflow_yaml)
        return
    
    if args.status:
        show_status(args.workflow_yaml)
        return
    
    print("\n" + "="*60)
    print("L4 Test Environment Startup")
    print("="*60)
    print(f"Workflow: {args.workflow_yaml}")

    if not check_hermes():
        sys.exit(1)

    if not preflight_config(args.workflow_yaml):
        print("\n配置不完整，请先补齐上面标 [X] 的项。")
        sys.exit(1)

    workflow_yaml = Path(args.workflow_yaml)
    config = yaml.safe_load(workflow_yaml.read_text(encoding="utf-8"))
    bastion_profile = config.get("bastion", {}).get("profile", "t_h20")

    if not ensure_bastion_daemon(bastion_profile):
        sys.exit(1)
    
    if not start_gateways(args.workflow_yaml):
        sys.exit(1)
    
    if not start_supervisor(args.workflow_yaml):
        sys.exit(1)
    
    print("\n" + "="*60)
    print("[OK] L4 Test Environment READY")
    print("="*60)
    print("\nNext Step:")
    print("  1. Send '跑 ut workflow' in Feishu apmm-ut group")
    print("  2. Confirm parameters in the Feishu card")
    print("  3. Watch executor → fixer → executor dependency chain")
    print("\nLogs:")
    print(f"  Gateway logs: {Path(args.workflow_yaml).parent.parent}/.agents/logs/")
    print(f"  Supervisor log: {Path(args.workflow_yaml).parent.parent}/.agents/logs/supervisor_ut-supervisor.log")


if __name__ == "__main__":
    main()