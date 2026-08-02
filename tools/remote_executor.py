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

    # Poll until terminal state
    deadline = time.monotonic() + timeout + 120  # generous margin
    poll_interval = 2  # seconds

    while time.monotonic() < deadline:
        sr = subprocess.run(
            [str(_BIFROST_BIN), "client", "status", task_id],
            capture_output=True, text=True, timeout=10,
            env=_bifrost_env(),
        )
        output = (sr.stdout or "") + "\n" + (sr.stderr or "")
        status_lower = output.lower()

        # Terminal states
        if "completed" in status_lower or "failed" in status_lower or "timeout" in status_lower:
            # Read result file directly from GPFS (bifrost writes results/<id>_result.json)
            return _fetch_bifrost_result(task_id, sr.stdout.strip())

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
