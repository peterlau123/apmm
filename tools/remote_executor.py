#!/usr/bin/env python3
"""
remote_executor.py - Unified remote command execution backend.

Drop-in replacement for the ``run_remote()`` pattern in execute_batch.py.
Supports two backends, switchable via workflow.yaml ``remote_backend``:

1. ``agent``  (default) - tools/agent.py SSH bastion daemon (legacy)
2. ``bifrost``          - bifrost CLI over GPFS shared storage

Both return the same dict shape:
    {"exit_code": int, "stdout": str, "stderr": str, "size_bytes": int|None}

Usage in scripts:
    from tools.remote_executor import run_remote
    result = run_remote("hostname", timeout=30, backend="bifrost")
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AGENT_PY = _PROJECT_ROOT / "tools" / "agent.py"

# bifrost binary + config (env var takes priority, then ~/.bifrost/settings.json)
_BIFROST_BIN = Path(os.environ.get(
    "BIFROST_BIN", "/gpfs/gcsp/liuxin/bifrost/target/release/bifrost"
))
_BIFROST_CONFIG = os.environ.get(
    "BIFROST_CONFIG", "/gpfs/gcsp/liuxin/bifrost_test/settings.json"
)

# ── Disconnect detection (shared with bastion_signals) ──────────────────────

_DISCONNECT_SIGNALS = (
    "daemon not reachable",
    "connection refused",
    "no route to host",
    "bastion disconnected",
    "ssh: connect to host",
)


def _is_disconnect_blob(blob: str) -> bool:
    if not blob:
        return False
    low = blob.lower()
    return any(sig in low for sig in _DISCONNECT_SIGNALS)


# ── Bifrost backend ──────────────────────────────────────────────────────────

def _bifrost_env() -> dict[str, str]:
    """Environment for bifrost CLI invocations."""
    env = dict(os.environ)
    if _BIFROST_CONFIG:
        env["BIFROST_CONFIG"] = _BIFROST_CONFIG
    return env


def _bifrost_health() -> bool:
    """Check if bifrost daemon is alive via CLI."""
    try:
        r = subprocess.run(
            [str(_BIFROST_BIN), "client", "status", "00000000-0000-0000-0000-000000000000"],
            capture_output=True, text=True, timeout=10,
            env=_bifrost_env(),
        )
        # Any non-panic response means the CLI can read GPFS.
        # The real daemon health is checked by attempting a submit.
        # ponytail: real health check requires MCP tool or heartbeat file stat;
        # for CLI path we just verify the binary runs and GPFS is accessible.
        return r.returncode in (0, 1)  # 1 = task not found (expected)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _run_bifrost(
    cmd: str,
    *,
    timeout: int = 600,
    profile: str = "t_h20",
    working_dir: Optional[str] = None,
) -> dict:
    """Execute a command via bifrost: submit -> poll -> fetch result.

    Raises ConnectionError if bifrost daemon is unavailable.
    """
    if not _BIFROST_BIN.exists():
        raise FileNotFoundError(f"bifrost binary not found: {_BIFROST_BIN}")

    # E2E timing: submit (t0) -> result fetched (t1)
    t0 = time.monotonic()

    # bifrost doesn't interpret shell features; wrap complex commands.
    # Heuristic: if the command contains shell metacharacters, wrap in sh -c.
    shell_chars = any(c in cmd for c in "&&|><$;`()")
    if shell_chars and not cmd.strip().startswith("sh -c"):
        cmd = f"sh -c {json.dumps(cmd)}"

    # Submit
    submit_args = [
        str(_BIFROST_BIN), "client", "submit",
        "--command", cmd,
        "--timeout", str(timeout),
    ]
    if working_dir:
        submit_args.extend(["--working-dir", working_dir])

    try:
        r = subprocess.run(
            submit_args, capture_output=True, text=True, timeout=30,
            env=_bifrost_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise ConnectionError(f"bifrost submit timed out: {e}") from e

    if r.returncode != 0:
        raise ConnectionError(f"bifrost submit failed: {r.stderr.strip()[:300]}")

    # Parse task_id from output: "Task ID: <uuid>"
    task_id = None
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("Task ID:"):
            task_id = line.split(":", 1)[1].strip()
            break
    if not task_id:
        raise ConnectionError(
            f"bifrost submit returned no task_id: {r.stdout[:200]}"
        )
    # DEBUG 2026-08-04: 打印 task_id 定位任务去向
    if os.environ.get("BIFROST_DEBUG_TASK"):
        print(f"[DBG-task] submitted {task_id} storage={_get_bifrost_shared_storage()} "
              f"cmd={cmd[:80]}", flush=True)

    # Poll until terminal state: watch the result file directly on GPFS.
    # A local stat() on GPFS is ~1ms (vs spawning `bifrost client status`,
    # which costs ~30ms + process startup each poll). Tight interval keeps
    # e2e latency ≈ server execution time, not poll cadence.
    deadline = time.monotonic() + timeout + 120  # generous margin
    poll_interval = 0.2  # seconds - GPFS stat is cheap
    shared_storage = _get_bifrost_shared_storage()
    result_file = shared_storage / "results" / f"{task_id}_result.json"

    while time.monotonic() < deadline:
        if result_file.exists():
            # Read result file directly from GPFS (bifrost writes results/<id>_result.json)
            result = _fetch_bifrost_result(task_id, "")
            # E2E timing: total wall-clock from submit to result fetched
            result["e2e_duration_ms"] = int((time.monotonic() - t0) * 1000)
            return result
        time.sleep(poll_interval)

    raise TimeoutError(f"bifrost task {task_id} did not complete within {timeout + 120}s")


def _fetch_bifrost_result(task_id: str, status_output: str) -> dict:
    """Read the result JSON from GPFS shared storage.

    bifrost writes results to <shared_storage>/results/<task_id>_result.json.
    We parse it directly rather than via CLI (no separate result subcommand).
    """
    # Determine shared_storage from config
    shared_storage = _get_bifrost_shared_storage()
    result_file = shared_storage / "results" / f"{task_id}_result.json"

    if not result_file.exists():
        # Result file not written yet; return what we have from status
        return {
            "exit_code": -1,
            "stdout": status_output,
            "stderr": f"Result file not found: {result_file}",
            "size_bytes": None,
        }

    try:
        data = json.loads(result_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Failed to read result: {e}",
            "size_bytes": None,
        }

    output = data.get("output", {})
    return {
        "exit_code": output.get("exit_code", -1),
        "stdout": output.get("stdout", ""),
        "stderr": output.get("stderr", ""),
        "size_bytes": len(output.get("stdout", "").encode("utf-8")),
    }


def _get_bifrost_shared_storage() -> Path:
    """Parse shared_storage path from bifrost settings.json."""
    config_path = Path(_BIFROST_CONFIG)
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return Path(cfg["shared_storage"])
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    # Fallback
    return Path("/gpfs/gcsp/liuxin/bifrost_test")


# ── Agent.py backend (legacy, unchanged) ─────────────────────────────────────

def _run_agent_py(
    cmd: str,
    *,
    timeout: int = 600,
    profile: str = "t_h20",
) -> dict:
    """Execute via tools/agent.py SSH bastion daemon (original run_remote)."""
    args = [
        sys.executable, str(_AGENT_PY),
        "-p", profile,
        "run", "--timeout", str(timeout),
        cmd,
    ]
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 60,
            cwd=str(_PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired as e:
        raise ConnectionError(f"agent.py timed out: {e}") from e

    stdout = r.stdout or ""
    stderr = r.stderr or ""

    if r.returncode != 0 and _is_disconnect_blob(stdout + "\n" + stderr):
        raise ConnectionError(f"bastion daemon unreachable: {stderr.strip()[:200]}")

    return {
        "exit_code": r.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "size_bytes": None,
    }


# ── Public API ───────────────────────────────────────────────────────────────

def run_remote(
    cmd: str,
    *,
    timeout: int = 600,
    profile: str = "t_h20",
    backend: Optional[str] = None,
    working_dir: Optional[str] = None,
) -> dict:
    """Run a shell command on the remote H20 node.

    Args:
        cmd: Shell command to execute.
        timeout: Wall-clock timeout in seconds.
        profile: Remote profile name (agent.py: t_h20/t_ascend).
        backend: "bifrost" or "agent". If None, reads BIFROST_BACKEND env var,
                 defaults to "agent".
        working_dir: Working directory on the remote node (bifrost only).

    Returns:
        {"exit_code": int, "stdout": str, "stderr": str, "size_bytes": int|None}

    Raises:
        ConnectionError: If the remote backend is unreachable.
    """
    if backend is None:
        backend = os.environ.get("REMOTE_BACKEND", "agent")

    if backend == "bifrost":
        return _run_bifrost(cmd, timeout=timeout, profile=profile, working_dir=working_dir)
    else:
        return _run_agent_py(cmd, timeout=timeout, profile=profile)


# ── GPU 探查与动态并行度 ────────────────────────────────────────────────────

# GPU 空闲判定阈值: 利用率 < 5% 且显存占用 < 500MB 视为空闲
_GPU_IDLE_UTIL_PCT = 5.0
_GPU_IDLE_MEM_MIB = 500


def probe_gpus(timeout: int = 60, backend: str = "bifrost") -> dict:
    """Probe GPU availability on the remote node.

    Runs ``nvidia-smi`` remotely and parses per-GPU utilization/memory.
    Returns:
        {
          "total": int,          # total GPU count
          "idle": int,           # idle (free) GPU count
          "busy": int,           # busy GPU count
          "gpus": [{"index": int, "util_pct": float, "mem_used_mib": int, "idle": bool}, ...]
        }
    """
    cmd = (
        "nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader"
    )
    result = run_remote(cmd, timeout=timeout, backend=backend)
    if result["exit_code"] != 0:
        raise ConnectionError(
            f"GPU probe failed (exit {result['exit_code']}): {result['stderr'][:300]}"
        )

    gpus = []
    for line in (result["stdout"] or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
            util = float(parts[1].rstrip("%"))
            mem = int(parts[2].split()[0])  # "0 MiB" -> 0
        except ValueError:
            continue
        idle = util < _GPU_IDLE_UTIL_PCT and mem < _GPU_IDLE_MEM_MIB
        gpus.append({"index": idx, "util_pct": util, "mem_used_mib": mem, "idle": idle})

    idle = sum(1 for g in gpus if g["idle"])
    return {
        "total": len(gpus),
        "idle": idle,
        "busy": len(gpus) - idle,
        "gpus": gpus,
    }


def compute_parallelism(
    *,
    probe_result: Optional[dict] = None,
    max_parallel: int = 10,
    backend: str = "bifrost",
) -> int:
    """Determine parallelism from GPU availability.

    Priority:
      1. explicit probe_result (if given, no remote call)
      2. remote GPU probe (idle GPU count)
      3. fallback to max_parallel if probe fails

    Result is clamped to [1, max_parallel].
    """
    try:
        if probe_result is None:
            probe_result = probe_gpus(backend=backend)
        idle = probe_result.get("idle", 0)
        parallelism = idle if idle > 0 else 1
    except (ConnectionError, FileNotFoundError):
        parallelism = max_parallel

    return max(1, min(parallelism, max_parallel))


# ── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Quick smoke test: run 'hostname' on the remote node."""
    backend = sys.argv[1] if len(sys.argv) > 1 else "agent"
    print(f"Testing backend={backend}")
    try:
        result = run_remote("hostname", timeout=30, backend=backend)
        print(f"  exit_code: {result['exit_code']}")
        print(f"  stdout: {result['stdout'].strip()}")
        print(f"  stderr: {result['stderr'].strip()[:200]}")
        print(f"  size_bytes: {result['size_bytes']}")
        print("✓ OK" if result["exit_code"] == 0 else "✗ non-zero exit")
    except (ConnectionError, FileNotFoundError) as e:
        print(f"✗ {e}")
        sys.exit(1)
