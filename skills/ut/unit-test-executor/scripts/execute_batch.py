#!/usr/bin/env python3
"""
execute_batch.py - v5 batch executor (Worker)

v5 behavior:
- Runs pytest REMOTELY, redirecting ALL output to raw_log.txt on the remote
  (the only file written remotely).
- Runs a remote grep+tail on raw_log.txt, brings the text back, and writes
  summary.txt LOCALLY.
- batch_results.json (local) carries a `remote_log` pointer to the remote
  raw_log path, plus per-test entries with status + error_type.
- Worker NEVER retries internally.
- On Bastion disconnect (ConnectionError from run_remote), the executor calls
  BastionManager.mark_disconnected() and returns {"next_action": "wait", ...}
  WITHOUT writing batch_results.json and WITHOUT mutating manifest/test status.

Usage:
    python execute_batch.py --batch-config PATH --workflow-state PATH
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.shared import get_paths, get_config  # noqa: E402

# Local module imports (hyphenated dir → load by file)
import importlib.util as _ilu

_SCRIPT_DIR = Path(__file__).resolve().parent


def _load_local(name, filename):
    spec = _ilu.spec_from_file_location(name, _SCRIPT_DIR / filename)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_classifier = _load_local("_v5_classify_error", "classify_error.py")
classify = _classifier.classify

# BastionManager is imported lazily at the call site so tests can patch it
# on this module before instantiation.
try:
    from skills.ut.workflow.scripts.bastion_manager import BastionManager  # noqa: F401
except Exception:  # pragma: no cover - tests patch it directly
    BastionManager = None  # type: ignore[assignment]


# ── Remote call helper ────────────────────────────────────────────────────────

def run_remote(cmd: str, *, timeout: int = 600, profile: str = "t_h20") -> dict:
    """Run a shell command on the remote host via tools/agent.py.

    Returns {"exit_code": int, "stdout": str, "stderr": str, "size_bytes": int|None}.

    Raises ConnectionError if the bastion daemon is unreachable / disconnected.
    """
    agent_py = _project_root / "tools" / "agent.py"
    args = [
        sys.executable, str(agent_py),
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
            cwd=str(_project_root),
        )
    except subprocess.TimeoutExpired as e:
        raise ConnectionError(f"agent.py timed out: {e}") from e

    stdout = r.stdout or ""
    stderr = r.stderr or ""

    # Heuristic: agent.py / bastion daemon connection failures.
    disconnect_signals = (
        "daemon not reachable",
        "connection refused",
        "no route to host",
        "bastion disconnected",
        "ssh: connect to host",
    )
    blob = (stdout + "\n" + stderr).lower()
    if r.returncode != 0 and any(sig in blob for sig in disconnect_signals):
        raise ConnectionError(f"bastion daemon unreachable: {stderr.strip()[:200]}")

    return {
        "exit_code": r.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "size_bytes": None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now_iso_z() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify_for_test(summary_text: str, test_node: str):
    """Find the line(s) in summary_text mentioning test_node and classify them.
    Falls back to whole summary if not found."""
    lines = [ln for ln in summary_text.splitlines() if test_node in ln]
    blob = "\n".join(lines) if lines else summary_text
    return classify(blob, test_node)


# ── Main entry ────────────────────────────────────────────────────────────────

def execute_batch(batch_config_path: Path, workflow_state_path: Path, *, exec_config: dict | None = None) -> dict:
    """Execute a batch of tests remotely; return a summary dict.

    Side effects on success:
      - writes <batch_dir>/batch_results.json
      - writes <batch_dir>/summary.txt

    On Bastion disconnect: writes neither; returns {"next_action": "wait", ...}.
    """
    batch_config_path = Path(batch_config_path)
    workflow_state_path = Path(workflow_state_path)

    batch_config = json.loads(batch_config_path.read_text(encoding="utf-8"))
    config = exec_config if exec_config is not None else get_config(workflow_state_path)

    batch_dir = batch_config_path.parent
    batch_id = batch_config["batch_id"]
    tests = batch_config["tests"]
    test_nodes = [t["test_node"] for t in tests]

    remote_server = config.get("remote_server", "t_h20")
    docker_container = config.get("docker_container", "v0.13.0_torch2.5.1_compile")
    pytest_args = config.get("pytest_args", "-v --tb=long")
    timeout = config.get("timeout", 600)
    remote_log_dir = config.get(
        "remote_log_dir", "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"
    )

    raw_log_path = f"{remote_log_dir}/{batch_id}/raw_log.txt"
    test_paths = " ".join(test_nodes)

    # Remote pytest: ALL output -> raw_log.txt on remote (the only remote write).
    pytest_cmd = (
        f"mkdir -p {remote_log_dir}/{batch_id} && "
        f"cd /gpfs/gcsp/M2.7_verify/vllm && "
        f"python3 -m pytest {test_paths} {pytest_args} > {raw_log_path} 2>&1"
    )
    pytest_docker_cmd = (
        f"sudo docker exec {docker_container} bash -c '{pytest_cmd}'"
    )

    started_at = _utc_now_iso_z()
    print(f"[INFO] Executing {len(tests)} tests remotely → {raw_log_path}")

    try:
        pytest_res = run_remote(
            pytest_docker_cmd, timeout=timeout, profile=remote_server
        )
    except ConnectionError as e:
        # Bastion disconnect: do NOT write batch_results.json, do NOT mutate
        # manifest/test status. Notify BastionManager and tell the caller to
        # wait. Stage 2 will re-select the batch later.
        reason = str(e)
        print(f"[WARN] Bastion disconnect: {reason}")
        try:
            mgr = BastionManager(  # type: ignore[misc]
                workspace=str(_project_root),
                profile=remote_server,
                workflow_state_path=str(workflow_state_path),
            )
            mgr.mark_disconnected(reason=reason)
        except Exception as inner:  # pragma: no cover
            print(f"[WARN] mark_disconnected failed: {inner}")
        return {
            "batch_id": batch_id,
            "next_action": "wait",
            "reason": reason,
        }

    # Second remote call: extract a summary via grep+tail on raw_log.txt.
    summary_extract_cmd = (
        f"sudo docker exec {docker_container} bash -c "
        f"\"grep -E '(PASSED|FAILED|ERROR|SKIPPED)' {raw_log_path} ; "
        f"echo '----'; tail -50 {raw_log_path}\""
    )
    try:
        summary_res = run_remote(
            summary_extract_cmd, timeout=60, profile=remote_server
        )
        summary_text = summary_res.get("stdout", "")
    except ConnectionError as e:
        # Disconnect on the summary call: same wait policy.
        reason = str(e)
        print(f"[WARN] Bastion disconnect during summary extract: {reason}")
        try:
            mgr = BastionManager(  # type: ignore[misc]
                workspace=str(_project_root),
                profile=remote_server,
                workflow_state_path=str(workflow_state_path),
            )
            mgr.mark_disconnected(reason=reason)
        except Exception:
            pass
        return {
            "batch_id": batch_id,
            "next_action": "wait",
            "reason": reason,
        }

    # Write summary.txt LOCALLY (next to batch_results.json).
    summary_path = batch_dir / "summary.txt"
    summary_path.write_text(summary_text or "", encoding="utf-8")

    finished_at = _utc_now_iso_z()
    captured_at = finished_at

    size_bytes = pytest_res.get("size_bytes")
    if not isinstance(size_bytes, int):
        # Fall back to the local summary length as a coarse signal; the real
        # value is written by parse-side tooling that may stat the remote file.
        size_bytes = len((summary_text or "").encode("utf-8"))

    # Per-test classification.
    test_entries = []
    counters = {"passed": 0, "failed": 0, "error": 0, "skipped": 0,
                "retriable_error": 0}
    for t in tests:
        status, error_type = _classify_for_test(summary_text, t["test_node"])
        counters[status] = counters.get(status, 0) + 1
        test_entries.append({
            "id": t["id"],
            "test_node": t["test_node"],
            "status": status,
            "error_type": error_type,
            "duration_ms": 0,
        })

    batch_results = {
        "batch_id": batch_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "timeout": timeout,
        "exit_code": pytest_res.get("exit_code", 0),
        "remote_log": {
            "host": remote_server,
            "container": docker_container,
            "raw_log_path": raw_log_path,
            "size_bytes": size_bytes,
            "captured_at": captured_at,
        },
        "tests": test_entries,
        "statistics": {
            "total": len(tests),
            "passed": counters.get("passed", 0),
            "failed": counters.get("failed", 0),
            "error": counters.get("error", 0),
            "skipped": counters.get("skipped", 0),
            "retriable_error": counters.get("retriable_error", 0),
        },
    }

    output_path = batch_dir / "batch_results.json"
    output_path.write_text(
        json.dumps(batch_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[OK] {output_path}")

    return {
        "batch_id": batch_id,
        "batch_results_path": str(output_path),
        "stats": batch_results["statistics"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-config", required=True)
    parser.add_argument("--workflow-state", required=True)
    args = parser.parse_args()

    result = execute_batch(Path(args.batch_config), Path(args.workflow_state))
    print(json.dumps(result, indent=2))
