#!/usr/bin/env python3
"""
ut_runner.py - UT Workflow shared runner library (v5)

v5 refactor: the in-process Stage 2-5 loop and the kanban-mode polling loop
have moved out of this module. Stage logic now lives in the four Worker
SKILLs, driven by `skills/ut/workflow-loop-core/SKILL.md`. Channel SKILLs
(`skills/ut/workflow` for linear, `skills/ut/hermes-workflow` for kanban)
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

SCRIPT_DIR = Path(__file__).resolve().parent          # skills/ut/shared/
SKILL_DIR = SCRIPT_DIR.parent                          # skills/ut/
PROJECT_ROOT = SKILL_DIR.parent.parent                 # apmm/

# Allow imports from skills/ut/shared and terminal-workflow/scripts (bastion_manager, feishu_api)
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SKILL_DIR / "terminal-workflow" / "scripts"))

from bastion_manager import BastionManager
from feishu_api import FeishuAPI

# Hermes Kanban API for task creation
try:
    from hermes_cli.kanban_db import connect, create_task
except ImportError:
    # Fallback for environments without hermes_cli
    connect = None
    create_task = None


# ── Helpers ────────────────────────────────────────────────────────────────────

# Feishu group-message command parsing.
# Layer 1 (regex): deterministic atomic commands.
# Layer 2 (LLM, P3): free-text intent classification — falls through here.
# Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §4

_WHITELIST = {"batch_size", "pytest_args", "max_retry_per_test", "timeout"}

# All Layer-1 patterns are STRICT anchored matches (no substring matching).
# Substring matches in v0 caused "稍后结束这个" to fire `stop`.
_OTP_RE          = re.compile(r"^\s*(\d{6})\s*$")
_OTP_WITH_ID_RE  = re.compile(r"^\s*OTP\s+(\w+)\s+(\d{6})\s*$", re.IGNORECASE)
_STOP_RE         = re.compile(r"^\s*(?:结束|取消|终止|停止|stop)\s*$", re.IGNORECASE)
_PAUSE_RE        = re.compile(r"^\s*(?:暂停|pause)\s*$", re.IGNORECASE)
_RESUME_RE       = re.compile(r"^\s*(?:继续|恢复|resume)\s*$", re.IGNORECASE)
_CHANGE_RE       = re.compile(r"^\s*改\b")   # "改 KEY=VAL" prefix
_KV_RE           = re.compile(r"(\w+)\s*=\s*(\S+)")


@dataclass
class Command:
    """Parsed Feishu message — output of Layer 1 (regex) or Layer 2 (LLM).

    intent: canonical intent label (see §4.4 of the spec).
    confidence: 1.0 for Layer-1 regex hits; 0..1 for Layer-2 LLM classifications.
    args: intent-specific payload (e.g. {"code": "123456"} for otp,
          {"batch_size": "4"} for change_config).
    source: "regex" | "llm" — which layer produced this Command.
    raw_text: the original message text, preserved for logging/audit.
    """
    intent: Literal[
        "otp", "otp_with_id", "stop", "pause", "resume", "change_config",
        "start_l1", "start_l2", "start_l3", "start_l4",
        "start_production", "unknown",
    ]
    confidence: float
    args: dict = field(default_factory=dict)
    source: Literal["regex", "llm"] = "regex"
    raw_text: str = ""


# Legacy {type, payload} → new intent mapping for the back-compat adapter.
_LEGACY_TYPE_FOR_INTENT = {
    "otp": "otp",
    "otp_with_id": "otp",   # legacy callers only saw "otp"
    "stop": "stop",
    "pause": "pause",
    "resume": "resume",
    "change_config": "change_config",
}


def parse_command(text):
    """Parse a Feishu group message via Layer 1 (regex). Returns Command or None.

    Returns None on no Layer-1 match — caller should fall through to Layer 2
    (LLM classification, P3). Callers that want the legacy ``{type, payload}``
    shape should use :func:`parse_command_as_dict` instead.
    """
    if text is None:
        return None
    raw = text
    t = text.strip()

    if not t:
        return None

    # OTP — strict 6 digits, optionally prefixed by "OTP <request_id>".
    m = _OTP_WITH_ID_RE.match(t)
    if m:
        return Command(intent="otp_with_id", confidence=1.0,
                       args={"request_id": m.group(1), "code": m.group(2)},
                       source="regex", raw_text=raw)
    m = _OTP_RE.match(t)
    if m:
        return Command(intent="otp", confidence=1.0,
                       args={"code": m.group(1)},
                       source="regex", raw_text=raw)

    if _STOP_RE.match(t):
        return Command(intent="stop", confidence=1.0, source="regex", raw_text=raw)
    if _PAUSE_RE.match(t):
        return Command(intent="pause", confidence=1.0, source="regex", raw_text=raw)
    if _RESUME_RE.match(t):
        return Command(intent="resume", confidence=1.0, source="regex", raw_text=raw)

    if _CHANGE_RE.match(t):
        payload = {k: v for k, v in _KV_RE.findall(t) if k in _WHITELIST}
        return Command(intent="change_config", confidence=1.0,
                       args=payload, source="regex", raw_text=raw)

    return None


def parse_command_as_dict(text):
    """Back-compat adapter — returns the legacy ``{"type", "payload"}`` shape.

    Maps the new ``Command`` dataclass back to the v4 ``{type, payload}``
    dict so existing callers (archive/supervisor_feishu_listen.py, old tests)
    keep working. New code should use :func:`parse_command` directly.
    """
    cmd = parse_command(text)
    if cmd is None:
        return None
    legacy_type = _LEGACY_TYPE_FOR_INTENT.get(cmd.intent, cmd.intent)
    return {"type": legacy_type, "payload": dict(cmd.args)}


# ── Layer 2 — LLM intent classification ───────────────────────────────────────
# Free-text messages that fall through Layer 1 land here. The classifier
# returns a Command with source="llm". `start_*` results are still gated by a
# confirmation card downstream (spec §4.5) — this layer only proposes intent.

_VALID_LLM_INTENTS = frozenset({
    "start_l1", "start_l2", "start_l3", "start_l4",
    "start_production", "change_config", "unknown",
})

# Strip an outer ```json … ``` fence (or bare ``` … ```) if the model adds one
# despite the SOUL.md instruction. Match the longest fenced block.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.+?)\s*```$", re.DOTALL | re.IGNORECASE)


def _strip_json_fence(s: str) -> str:
    s = s.strip()
    m = _JSON_FENCE_RE.match(s)
    return m.group(1).strip() if m else s


def _unknown(raw_text: str) -> "Command":
    """Fallback Command for any malformed / off-rail LLM output."""
    return Command(intent="unknown", confidence=0.0, args={},
                   source="llm", raw_text=raw_text)


def classify_intent_llm(text, llm_output) -> "Command":
    """Layer 2: parse & validate the Agent's self-produced intent classification.

    The ut-supervisor Agent reads SOUL.md §Intent classification, uses its
    own LLM reasoning on the free-text message, and produces a JSON string.
    This function validates & parses that JSON into a ``Command``.

    Parameters
    ----------
    text:
        The Feishu message text (used only for ``raw_text`` in the result).
    llm_output:
        The JSON string the Agent produced (expected to conform to SOUL.md
        schema: ``{"intent": ..., "confidence": ..., "args": {}}``).

    Returns
    -------
    Command with ``source="llm"``. ``intent="unknown"`` on:
      - ``llm_output`` not valid JSON or not a dict
      - ``intent`` not in the SOUL.md vocabulary
      - ``confidence`` not numeric
      - ``text`` is None/empty

    The function never raises; classification is best-effort.
    """
    raw_text = text or ""
    if not raw_text.strip():
        return _unknown(raw_text)

    if not isinstance(llm_output, str):
        return _unknown(raw_text)

    try:
        parsed = json.loads(_strip_json_fence(llm_output))
    except (ValueError, json.JSONDecodeError):
        return _unknown(raw_text)

    if not isinstance(parsed, dict):
        return _unknown(raw_text)

    intent = parsed.get("intent")
    confidence = parsed.get("confidence")
    args = parsed.get("args", {})

    if intent not in _VALID_LLM_INTENTS:
        return _unknown(raw_text)
    if not isinstance(confidence, (int, float)):
        return _unknown(raw_text)
    if not isinstance(args, dict):
        args = {}

    conf = max(0.0, min(1.0, float(confidence)))

    return Command(intent=intent, confidence=conf, args=args,
                   source="llm", raw_text=raw_text)


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



def _ensure_test_load(workflow_yaml_path, run_dir, state_path):
    """Ensure test_load exists. Generate if missing.

    Called after init_workflow_state.py (new run) or on resume (if test_load missing).
    Reads test_load.count from workflow.yaml (default 1000).
    """
    state = _read_json(state_path)
    test_load_path = state.get("paths", {}).get("test_load", "")

    if test_load_path and Path(test_load_path).exists():
        print(f"[ut_runner] test_load exists: {test_load_path}")
        return

    # Read count from workflow.yaml
    count = 1000
    try:
        cfg = yaml.safe_load(Path(workflow_yaml_path).read_text(encoding="utf-8"))
        count = cfg.get("workflow", {}).get("test_load", {}).get("count", 1000)
    except Exception:
        pass

    # Find manifest path from state
    manifest_path = state.get("paths", {}).get("manifest", str(run_dir / "manifest.json"))

    print(f"[ut_runner] Generating test_load (count={count})...")
    gtl_script = str(PROJECT_ROOT / "tasks" / "ut" / "scripts" / "generate_test_load.py")
    rc, stdout, stderr = _run_py(
        [gtl_script,
         "--manifest-path", manifest_path,
         "--count", str(count),
         "--output-dir", str(run_dir),
         "--workflow-state", str(state_path)],
        timeout=60,
    )
    if rc != 0:
        print(f"[ut_runner] generate_test_load failed: {stderr}")
        sys.exit(1)
    try:
        sys.stdout.write(stdout + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(stdout.encode("ascii", errors="replace").decode("ascii") + "\n")

def init_or_resume(workflow_yaml_path, resume_from):
    """Initialize a new run or resume from existing. Returns (run_dir, state_path, state, iteration)."""
    if resume_from:
        run_dir = Path(resume_from)
        state_path = run_dir / "workflow_state.json"
        state = _read_json(state_path)
        iteration = state.get("iteration", 0)
        # Ensure test_load exists on resume (auto-generate if missing)
        _ensure_test_load(workflow_yaml_path, run_dir, state_path)
        state = _read_json(state_path)
        print(f"[ut_runner] Resumed from {run_dir}, iteration={iteration}")
    else:
        init_script = str(SCRIPT_DIR / "init_workflow_state.py")
        rc, stdout, stderr = _run_py(
            [init_script, "--workflow-yaml", str(workflow_yaml_path)],
            timeout=30,
        )
        if rc != 0:
            print(f"[ut_runner] Init failed: {stderr}")
            sys.exit(1)
        # Windows GBK stdout can't render non-ASCII (✓ ⚠ etc.) coming from the
        # init subprocess — coerce to ascii-safe before printing so the runner
        # doesn't crash on the very first I/O.
        try:
            sys.stdout.write(stdout + "\n")
        except UnicodeEncodeError:
            sys.stdout.write(stdout.encode("ascii", errors="replace").decode("ascii") + "\n")

        pointer = _read_json(PROJECT_ROOT / ".agents" / "current_run.json")
        run_dir = Path(pointer["run_dir"])
        state_path = run_dir / "workflow_state.json"
        state = _read_json(state_path)
        iteration = 0

        # Auto-generate test_load after init (new run)
        _ensure_test_load(workflow_yaml_path, run_dir, state_path)
        # Reload state to get updated test_load path
        state = _read_json(state_path)

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
            print(f"[ut_runner] Feishu init failed: {e}")
    return None


def _setup_bastion(workspace, bastion_cfg, remote_server, feishu_config_path, state_path):
    """Create and connect BastionManager. Returns instance or None."""
    if not bastion_cfg:
        print("[ut_runner] No bastion config, skipping bastion management")
        return None

    bastion = BastionManager(
        workspace=workspace,
        profile=bastion_cfg.get("profile", remote_server),
        feishu_config_path=feishu_config_path,
        workflow_state_path=str(state_path),
    )
    bastion._heartbeat_interval = bastion_cfg.get("heartbeat_interval", 15)

    print("[ut_runner] Checking bastion connectivity...")
    if not bastion.ensure_connected(reason="startup", stage="init"):
        print("[ut_runner] Bastion not available, aborting")
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

def validate_required_config(
    cfg: dict, *, channel: str = "hermes"
) -> tuple[bool, list[str]]:
    """Preflight a workflow.yaml dict. Returns (ok, missing_keys).

    A config is acceptable if:
      - input_filter.test_list_path OR input_filter.manifest_source is set, AND
      - config.remote_server is set, AND
      - channel/kanban interlock (see below) is satisfied.

    Channel × kanban interlock:
      - channel="linear" (ut/workflow): kanban.enabled MUST NOT be true.
        Linear channel runs Stage 2-5 in-process and cannot drive the 3-Gateway
        Kanban dispatch model; mixing the two would deadlock the dispatcher.
      - channel="hermes" (ut/hermes-workflow): kanban.enabled may be true or
        false (linear-mode supervisor or kanban-mode supervisor both supported).
    """
    missing: list[str] = []
    input_filter = cfg.get("input_filter") or {}
    if not input_filter.get("test_list_path") and not input_filter.get("manifest_source"):
        missing.append("input_filter.test_list_path|manifest_source")

    config = cfg.get("config") or {}
    if not config.get("remote_server"):
        missing.append("config.remote_server")

    kanban_on = (cfg.get("kanban") or {}).get("enabled") is True
    if channel == "linear" and kanban_on:
        missing.append(
            "kanban.enabled=true 不允许在 ut/workflow 线性通道下运行 — "
            "请改为 false，或改用 ut/hermes-workflow"
        )

    return (len(missing) == 0), missing


# Worker gateway profiles managed by Hermes in kanban mode.
KANBAN_GATEWAY_PROFILES = ("ut-batch-selector", "ut-executor", "ut-fixer", "ut-manifest-updater")


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


def refresh_test_load_stats(state_path, test_load_path) -> dict:
    """Tally test statuses from the test_load into state['test_load_stats'].

    Feeds check_stop_conditions. Returns the tally dict.
    """
    test_load = _read_json(test_load_path)
    stats: dict = {}
    for t in test_load.get("tests", []):
        status = t.get("status")
        stats[status] = stats.get(status, 0) + 1

    state = _read_json(state_path)
    state["test_load_stats"] = stats
    _write_json(state_path, state)
    return stats




def check_stop_conditions(state_path) -> tuple[bool, str, str]:
    """Terminal check: (done, reason, status).

    done = True iff test_load_stats.pending == 0 AND running == 0.
    status is one of {"completed", ""} (channels add their own statuses).
    """
    state = _read_json(state_path)
    stats = state.get("test_load_stats") or {}
    pending = stats.get("pending", 1)  # default 1 → not done
    running = stats.get("running", 0)

    if pending == 0 and running == 0:
        return True, "pending_count == 0", "completed"
    return False, "", ""


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    """Deprecation shim. ut_runner is an import-only library.

    Stage logic moved to skills/ut/workflow-loop-core/SKILL.md and the four
    Worker SKILLs. Use a channel SKILL (ut/workflow or hermes-workflow) to
    actually drive a run.
    """
    parser = argparse.ArgumentParser(
        description="ut_runner (v5): import-only library; stage logic moved to loop_core"
    )
    parser.add_argument("--workflow-yaml", default=None, help="(unused in v5)")
    parser.add_argument("--resume-from", default=None, help="(unused in v5)")
    parser.parse_args()

    print(
        "[ut_runner] v5 deprecation: this module no longer runs the workflow.\n"
        "  - Linear supervisor: load skills/ut/terminal-workflow/SKILL.md\n"
        "  - Kanban / Hermes:   load skills/ut/hermes-workflow/SKILL.md\n"
        "  Both delegate Stage 2-5 to skills/ut/workflow-loop-core."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
