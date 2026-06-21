#!/usr/bin/env python3
"""
hermes_runner.py - UT Workflow runner for Hermes (v5: import-only library)

v5 refactor: the in-process Stage 2-5 loop and the kanban-mode polling loop
have moved out of this module. Stage logic now lives in the four Worker
SKILLs, driven by `skills/ut/workflow_loop_core/SKILL.md`. Channel SKILLs
(`skills/ut/workflow` for linear, `skills/ut/hermes_workflow` for kanban)
wire the loop with channel-specific callbacks.

This module now provides:
  - init_or_resume(workflow_yaml, resume_from)  → run_dir/state/iteration
  - _setup_feishu() / send_feishu_card(...)     → one-way Feishu progress
  - _setup_bastion(...)                          → single ensure_connected probe
  - validate_required_config(cfg)               → config preflight
  - check_gateways_alive()                       → kanban gateway probe
  - apply_pending_config(state_path)            → reconfigure merge
  - check_stop_conditions(state_path)           → terminal check

Running this file directly is a no-op (prints a deprecation notice).

Design: tasks/ut/docs/discussions/2026-06-18-hermes-runner-bastion-otp-design.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent

# Allow imports from skills/ut/shared and workflow/scripts
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from bastion_manager import BastionManager
from feishu_api import FeishuAPI


# ── Helpers ────────────────────────────────────────────────────────────────────

# Feishu group-message command parsing (config-change whitelist).
_WHITELIST = {"batch_size", "pytest_args", "max_retry_per_test", "timeout"}
_STOP = ("结束", "终止", "停止")
_PAUSE = ("暂停",)
_RESUME = ("继续",)
_OTP_RE = re.compile(r"^\s*(\d{6})\s*$")
_KV_RE = re.compile(r"(\w+)\s*=\s*(\S+)")


def parse_command(text: str):
    """Parse a Feishu group message into a structured command dict, or None."""
    t = text.strip()
    if any(k in t for k in _STOP):
        return {"type": "stop", "payload": {}}
    if any(k in t for k in _PAUSE):
        return {"type": "pause", "payload": {}}
    if any(k in t for k in _RESUME):
        return {"type": "resume", "payload": {}}
    m = _OTP_RE.match(t)
    if m:
        return {"type": "otp", "payload": {"code": m.group(1)}}
    if t.startswith("改"):
        return {"type": "change_config",
                "payload": {k: v for k, v in _KV_RE.findall(t) if k in _WHITELIST}}
    return None


def _load_yaml(path):
    """Load a YAML file, returning {} on failure."""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_py(args, cwd=None, timeout=120):
    """Run a Python script and return (rc, stdout, stderr)."""
    cmd = [sys.executable] + args
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd or PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"


# ── Shared: Init & Bastion ─────────────────────────────────────────────────────

def init_or_resume(workflow_yaml_path, resume_from):
    """Initialize a new run or resume from existing. Returns (run_dir, state_path, state, iteration)."""
    if resume_from:
        run_dir = Path(resume_from)
        state_path = run_dir / "workflow_state.json"
        state = _read_json(state_path)
        iteration = state.get("iteration", 0)
        print(f"[hermes_runner] Resumed from {run_dir}, iteration={iteration}")
    else:
        init_script = str(SCRIPT_DIR / "init_workflow_state.py")
        rc, stdout, stderr = _run_py(
            [init_script, "--workflow-yaml", str(workflow_yaml_path)],
            timeout=30,
        )
        if rc != 0:
            print(f"[hermes_runner] Init failed: {stderr}")
            sys.exit(1)
        print(stdout)

        pointer = _read_json(PROJECT_ROOT / ".agents" / "current_run.json")
        run_dir = Path(pointer["run_dir"])
        state_path = run_dir / "workflow_state.json"
        state = _read_json(state_path)
        iteration = 0

    return run_dir, state_path, state, iteration


# Backwards-compatible alias for callers that imported the private name.
_init_or_resume = init_or_resume


def _setup_feishu():
    """Create FeishuAPI instance if config exists. Returns instance or None."""
    feishu_config_path = os.environ.get(
        "FEISHU_CONFIG",
        str(PROJECT_ROOT / ".agents" / "feishu_config.json"),
    )
    if Path(feishu_config_path).exists():
        try:
            return FeishuAPI(feishu_config_path)
        except Exception as e:
            print(f"[hermes_runner] Feishu init failed: {e}")
    return None


def _setup_bastion(workspace, bastion_cfg, remote_server, feishu_config_path, state_path):
    """Create and connect BastionManager. Returns instance or None."""
    if not bastion_cfg:
        print("[hermes_runner] No bastion config, skipping bastion management")
        return None

    bastion = BastionManager(
        workspace=workspace,
        profile=bastion_cfg.get("profile", remote_server),
        feishu_config_path=feishu_config_path,
        workflow_state_path=str(state_path),
    )
    bastion._heartbeat_interval = bastion_cfg.get("heartbeat_interval", 15)

    print("[hermes_runner] Checking bastion connectivity...")
    if not bastion.ensure_connected(reason="startup", stage="init"):
        print("[hermes_runner] Bastion not available, aborting")
        return None

    return bastion


# ── Feishu notification (shared) ───────────────────────────────────────────────

def send_feishu_card(feishu, event, manifest, iteration, batch_id=None, reason=None,
                     mode=None):
    """Send a progress/completion/alert card via Feishu."""
    if not feishu:
        return

    stats = manifest.get("statistics", {})
    total = stats.get("total", 0)
    passed = stats.get("passed", 0)
    failed = stats.get("failed", 0)
    error = stats.get("error", 0)
    pending = stats.get("pending", 0)

    pct = (passed / total * 100) if total > 0 else 0
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    mode_tag = f" [{mode}]" if mode else ""

    event_config = {
        "progress": ("UT Progress", "blue", "📊"),
        "complete": ("UT Workflow 完成", "green", "🏆"),
        "alert": ("UT Workflow 告警", "red", "⚠️"),
        "paused": ("UT Workflow 暂停", "yellow", "⏸️"),
    }

    title, color, emoji = event_config.get(event, ("UT Workflow", "blue", "📊"))
    title += mode_tag

    lines = [
        f"{emoji} **{title}**",
        "",
        f"进度: {bar} {pct:.1f}%",
        f"通过: {passed} | 失败: {failed} | 错误: {error} | 待执行: {pending}",
        f"总测试: {total} | 迭代: {iteration}",
    ]
    if batch_id:
        lines.append(f"批次: {batch_id}")
    if reason:
        lines.append(f"原因: {reason}")

    try:
        feishu.send_card({
            "header": {"title": title, "template": color},
            "content": "\n".join(lines),
        })
    except Exception as e:
        print(f"  [feishu] Failed to send card: {e}")


# ── v5 API: config validation, gateway probe, reconfigure, terminal check ─────

def validate_required_config(cfg: dict) -> tuple[bool, list[str]]:
    """Preflight a workflow.yaml dict. Returns (ok, missing_keys).

    A config is acceptable if:
      - input_filter.test_list_path OR input_filter.manifest_source is set, AND
      - config.remote_server is set.
    """
    missing: list[str] = []
    input_filter = cfg.get("input_filter") or {}
    if not input_filter.get("test_list_path") and not input_filter.get("manifest_source"):
        missing.append("input_filter.test_list_path|manifest_source")

    config = cfg.get("config") or {}
    if not config.get("remote_server"):
        missing.append("config.remote_server")

    return (len(missing) == 0), missing


# Worker gateway profiles managed by Hermes in kanban mode.
KANBAN_GATEWAY_PROFILES = ("ut-orchestrator", "ut-executor", "ut-fixer")


def check_gateways_alive() -> dict:
    """Probe each Hermes Gateway profile via `hermes gateway list`.

    Uses the Hermes gateway registry (cross-platform) instead of systemd, so
    gateways started with `hermes gateway run` are detected on Windows too
    (no systemctl there). Returns {profile: bool}.
    """
    try:
        r = subprocess.run(
            ["hermes", "gateway", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {profile: False for profile in KANBAN_GATEWAY_PROFILES}
    if r.returncode != 0:
        return {profile: False for profile in KANBAN_GATEWAY_PROFILES}
    lines = r.stdout.splitlines()
    return {
        profile: any(profile in line and "✓" in line for line in lines)
        for profile in KANBAN_GATEWAY_PROFILES
    }


def get_execute_config(state_path) -> dict:
    """Flatten workflow_state nested config into the flat keys execute_batch expects."""
    c = _read_json(state_path).get("config", {})
    remote = c.get("remote", {})
    vllm_dir = remote.get("vllm_dir", "/gpfs/gcsp/M2.7_verify/vllm")
    return {
        "remote_server": remote.get("server", "t_h20"),
        "docker_container": remote.get("docker", "v0.13.0_torch2.5.1_compile"),
        "timeout": c.get("timeout", 600),
        "pytest_args": c.get("pytest_args", "-v --tb=long"),
        "remote_log_dir": c.get("remote_log_dir", f"{vllm_dir}/ut_logs"),
    }


def apply_pending_config(state_path) -> dict:
    """Merge state['pending_config'] into state['config'] and persist.

    Returns the merged effective config dict (state['config'] after merge).
    No-op if no pending_config is present.
    """
    state = _read_json(state_path)
    pending = state.get("pending_config") or {}
    effective = dict(state.get("config") or {})

    if pending:
        effective.update(pending)
        state["config"] = effective
        state["pending_config"] = {}
        state["last_update"] = datetime.now(timezone.utc).isoformat()
        _write_json(state_path, state)

    return effective


def refresh_manifest_stats(state_path, manifest_path) -> dict:
    """Tally test statuses from the manifest into state['manifest_stats'].

    Feeds check_stop_conditions. Returns the tally dict.
    """
    manifest = _read_json(manifest_path)
    stats: dict = {}
    for t in manifest.get("tests", []):
        status = t.get("status")
        stats[status] = stats.get(status, 0) + 1

    state = _read_json(state_path)
    state["manifest_stats"] = stats
    _write_json(state_path, state)
    return stats


def _load_fn(skill_dir: str, module: str, fn_name: str):
    """Load `skills/ut/<skill_dir>/scripts/<module>.py` and return `<fn_name>`.

    Skill dirs are hyphenated (e.g. manifest-updater) so they can't be imported
    as normal packages; load them by file path via importlib.
    """
    import importlib.util

    path = SKILL_DIR / skill_dir / "scripts" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(
        f"_hermes_{skill_dir.replace('-', '_')}_{module}", path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, fn_name)


def orchestrator_round(*, run_dir, manifest_path, prev_batch_dir, batch_size):
    """Kanban ut-orchestrator round: Stage 5 (reconcile prev) then Stage 2 (select next).

    Chains the REAL v5 Worker functions:
      - manifest-updater.update_manifest(manifest, batch_results, handled) → merged manifest
      - batch-selector.select_batch(manifest, batch_size) → list of selected tests
      - batch-selector.write_batch_config(path, batch_id, iteration, run_id, selected) → cfg

    Returns {"completed": bool, "next_batch": dict|None}.
    """
    update_manifest = _load_fn("manifest-updater", "update_manifest", "update_manifest")
    select_batch = _load_fn("batch-selector", "generate_batch", "select_batch")
    write_batch_config = _load_fn("batch-selector", "generate_batch", "write_batch_config")

    run_dir = Path(run_dir)
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Stage 5: reconcile previous batch results into the manifest.
    if prev_batch_dir is not None:
        br = Path(prev_batch_dir) / "batch_results.json"
        if br.exists():
            batch_results = json.loads(br.read_text(encoding="utf-8"))
            hp = Path(prev_batch_dir) / "handled_tests.json"
            handled = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {"tests": []}
            # update_manifest mutates manifest in place and returns it.
            manifest = update_manifest(manifest, batch_results, handled)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    # Stage 2: select the next batch. select_batch encapsulates v5 selectability;
    # an empty selection means nothing is left to run → completed.
    selected = select_batch(manifest, batch_size)
    if not selected:
        return {"completed": True, "next_batch": None}

    nb = f"batch_{len(list(run_dir.glob('batch_*'))) + 1:04d}"
    nd = run_dir / nb
    nd.mkdir(exist_ok=True)
    cfg = write_batch_config(
        path=nd / "batch_config.json",
        batch_id=nb,
        iteration=0,
        run_id=run_dir.name,
        selected=selected,
    )
    return {"completed": False, "next_batch": cfg}


def check_stop_conditions(state_path) -> tuple[bool, str, str]:
    """Terminal check: (done, reason, status).

    done = True iff manifest_stats.pending == 0 AND running == 0.
    status is one of {"completed", ""} (channels add their own statuses).
    """
    state = _read_json(state_path)
    stats = state.get("manifest_stats") or {}
    pending = stats.get("pending", 1)  # default 1 → not done
    running = stats.get("running", 0)

    if pending == 0 and running == 0:
        return True, "pending_count == 0", "completed"
    return False, "", ""


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    """Deprecation shim. hermes_runner is now an import-only library.

    Stage logic moved to skills/ut/workflow_loop_core/SKILL.md and the four
    Worker SKILLs. Use a channel SKILL (ut/workflow or hermes_workflow) to
    actually drive a run.
    """
    parser = argparse.ArgumentParser(
        description="hermes_runner (v5): import-only library; stage logic moved to loop_core"
    )
    parser.add_argument("--workflow-yaml", default=None, help="(unused in v5)")
    parser.add_argument("--resume-from", default=None, help="(unused in v5)")
    parser.parse_args()

    print(
        "[hermes_runner] v5 deprecation: this module no longer runs the workflow.\n"
        "  - Linear supervisor: load skills/ut/workflow/SKILL.md\n"
        "  - Kanban / Hermes:   load skills/ut/hermes_workflow/SKILL.md\n"
        "  Both delegate Stage 2-5 to skills/ut/workflow_loop_core."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
