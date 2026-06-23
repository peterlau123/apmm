#!/usr/bin/env python3
"""
execute_batch.py - v5 batch executor (Worker)

v5 behavior:
- Runs pytest REMOTELY under a remote bash watchdog (idle-timeout +
  wall-clock fallback per design 2026-06-23-pytest-timeout-redesign.md §4).
  All output redirected to ``<remote_log_dir>/<batch_id>/pytest_<batch_id>.log``
  on the remote (the only file written remotely).
- The watchdog kills pytest with SIGKILL when either the idle threshold
  (no log activity for ``pytest_idle_timeout`` seconds) or the wall-clock
  ceiling (``timeout`` seconds) is exceeded, exits 124, and appends a
  ``__WATCHDOG__:`` sentinel line to the log for downstream LLM analysis.
- Runs a remote grep+tail on the log, brings the text back, and writes
  summary.txt LOCALLY.
- batch_results.json (local) carries a `remote_log` pointer to the remote
  log path, plus per-test entries with status + error_type.
- Worker NEVER retries internally.
- On Bastion disconnect (ConnectionError from run_remote), the executor calls
  BastionManager.mark_disconnected() and returns {"next_action": "wait", ...}
  WITHOUT writing batch_results.json and WITHOUT mutating manifest/test status.

Usage:
    python execute_batch.py --batch-config PATH --workflow-state PATH
"""

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover — jsonschema is a hard runtime dep but
    jsonschema = None  # tests may patch / install on demand

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

# ── Schema (Type-B fabrication backstop) ──────────────────────────────────────
#
# We enforce that batch_results.json is shape-correct BEFORE writing it, so a
# bug in this executor (or a future hand-rolled LLM substitute) cannot silently
# emit drifted / fabricated payloads that look plausible but are wrong-schema.
# The canonical schema lives next to this file.
_SCHEMA_PATH = _SCRIPT_DIR.parent / "batch_results_schema.json"


def _load_schema():
    """Read the canonical batch_results_schema.json. Cached on first call."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_batch_results_or_raise(payload: dict) -> None:
    """Validate payload against batch_results_schema.json.

    Raises ValueError with a compact, readable message on the FIRST failure.
    Type-B fabrication defense: if the executor itself drifts, we surface that
    here rather than letting manifest-updater consume a malformed payload.
    """
    if jsonschema is None:  # pragma: no cover — environment misconfig
        raise RuntimeError(
            "jsonschema not installed; batch_results.json validation is "
            "mandatory (Type-B fabrication backstop)"
        )
    schema = _load_schema()
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as e:  # type: ignore[attr-defined]
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"batch_results.json violates schema at /{path}: {e.message}"
        ) from e

# BastionManager is imported lazily at the call site so tests can patch it
# on this module before instantiation.
try:
    from skills.ut.workflow.scripts.bastion_manager import BastionManager  # noqa: F401
except Exception:  # pragma: no cover - tests patch it directly
    BastionManager = None  # type: ignore[assignment]


# ── Watchdog template (固化 — see design §4; do NOT rewrite at call sites) ────
#
# Notes on shell-quoting choices:
#   - The script is wrapped in `bash -c '<...>'` by the caller, so it must
#     not contain ANY ASCII single quotes (`'`).
#   - All shell variables (`$PID`, `$NOW`, `$START`, `$LAST_MTIME`) are
#     resolved at RUNTIME on the remote host; Python f-string substitution
#     only fills in `{log_path}`, `{wall_timeout}`, `{idle_timeout}`, and
#     `{pytest_full_cmd}`.
#   - `stat -c %Y` is GNU coreutils standard (vLLM test container is Ubuntu).
#   - `kill -9` ensures hung children release the SSH session promptly.
WATCHDOG_TEMPLATE = (
    "mkdir -p $(dirname {log_path}) && "
    "( {pytest_full_cmd} ) > {log_path} 2>&1 &\n"
    "PID=$!\n"
    "START=$(date +%s)\n"
    "while kill -0 $PID 2>/dev/null; do\n"
    "  sleep 10\n"
    "  NOW=$(date +%s)\n"
    "  if [ $((NOW - START)) -gt {wall_timeout} ]; then\n"
    "    kill -9 $PID 2>/dev/null\n"
    '    echo "__WATCHDOG__: wall_clock_exceeded after $((NOW-START))s" '
    ">> {log_path}\n"
    "    exit 124\n"
    "  fi\n"
    "  if [ -f {log_path} ]; then\n"
    "    LAST_MTIME=$(stat -c %Y {log_path} 2>/dev/null || echo $NOW)\n"
    "    if [ $((NOW - LAST_MTIME)) -gt {idle_timeout} ]; then\n"
    "      kill -9 $PID 2>/dev/null\n"
    '      echo "__WATCHDOG__: idle_exceeded $((NOW-LAST_MTIME))s '
    '(no log activity)" >> {log_path}\n'
    "      exit 124\n"
    "    fi\n"
    "  fi\n"
    "done\n"
    "wait $PID\n"
    "exit $?\n"
)


def _build_watchdog_script(
    *, log_path: str, pytest_full_cmd: str,
    idle_timeout: int, wall_timeout: int,
) -> str:
    """Render the remote bash watchdog script.

    Public for unit tests (see test_execute_batch_watchdog.py).
    """
    if "'" in pytest_full_cmd or "'" in log_path:
        raise ValueError(
            "pytest_full_cmd / log_path may not contain single quotes "
            "(outer wrap uses bash -c '<...>')"
        )
    return WATCHDOG_TEMPLATE.format(
        log_path=log_path,
        pytest_full_cmd=pytest_full_cmd,
        idle_timeout=int(idle_timeout),
        wall_timeout=int(wall_timeout),
    )


def _wrap_with_docker_exec_b64(docker_container: str, inner_script: str) -> str:
    """Wrap a (possibly multi-line, possibly quote-laden) bash script for
    remote `sudo -n docker exec ... bash -c` execution, using base64 to
    bypass ALL shell-quoting / IFS / newline pitfalls along the route
    (local shell → agent.py → ssh → remote shell → bash -c).

    Two bugs root-caused 2026-06-23 fabricated run ut-20260623-223710 motivate
    this helper:

      (1) The previous single-quote inline form (`bash -c '<script>'`) lost
          everything after the first newline because some hop along the route
          treated newlines as command separators, so `pytest` never ran but
          the wrapper still exited 0/2 in <1s and the executor classified
          the empty summary as 3 × error / duration_ms=0.

      (2) `sudo` (without `-n`) on the bastion-side `infra` user — which is
          NOT in the docker group's sudoers TTY-less list — prompts for a
          password it can't read, producing a confusing exit code instead
          of running docker.

    The wrapper:
      - prefixes `sudo -n` so a missing NOPASSWD entry fails LOUD (rc != 0
        with `sudo: a password is required` in stderr) instead of hanging.
      - base64-encodes the inner script and decodes on the remote side, so
        no quoting / newline survives the trip needs to be reasoned about.
    """
    encoded = base64.b64encode(inner_script.encode("utf-8")).decode("ascii")
    # Outer quoting uses double quotes around a pure-ASCII payload (echo +
    # pipe + base64 chars). No single quotes, no newlines, no shell meta in
    # the encoded chunk → no quoting risk in any hop.
    return (
        f"sudo -n docker exec {docker_container} bash -c "
        f"\"echo {encoded} | base64 -d | bash\""
    )


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


def _node(t: dict) -> str:
    """Return a test's node id, tolerating either `test_node` (executor field)
    or `test_id` (batch-selector field). Prefers `test_node`."""
    return t.get("test_node") or t["test_id"]


def _classify_for_test(summary_text: str, test_node: str):
    """Find the line(s) in summary_text mentioning test_node and classify them.
    Falls back to whole summary if not found.

    Bug #2 fix: pytest abbreviates long parametrized test names with '::...'.
    We need to match using:
    1. Exact match (full test_node in line)
    2. Test file prefix match (tests/foo.py::Class::... matches tests/foo.py::Class::test_name)
    3. Summary section match (FAILED/EERROR lines have full names)
    """
    lines = [ln for ln in summary_text.splitlines() if test_node in ln]
    if lines:
        blob = "\n".join(lines)
        return classify(blob, test_node)

    # Bug #2 fix: Try prefix matching for abbreviated pytest output
    # Extract test file prefix (e.g., "tests/benchmarks/test_param_sweep.py::TestParameterSweepItem")
    test_file_prefix = test_node.split("::")[0] if "::" in test_node else test_node.split(" ")[0]
    class_prefix = test_node.rsplit("::", 1)[0] if "::" in test_node else test_file_prefix

    # Look for lines with matching prefix
    prefix_lines = [ln for ln in summary_text.splitlines()
                    if (test_file_prefix in ln or class_prefix in ln)
                    and any(s in ln for s in ("PASSED", "FAILED", "ERROR", "SKIPPED"))]

    if prefix_lines:
        # Count how many tests share this prefix
        # Use progress percentage to distinguish
        blob = "\n".join(prefix_lines)
        return classify(blob, test_node)

    # Fallback: use whole summary (all tests get same status)
    return classify(summary_text or "", test_node)


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
    test_nodes = [_node(t) for t in tests]

    remote_server = config.get("remote_server", "t_h20")
    docker_container = config.get("docker_container", "v0.13.0_torch2.5.1_compile")
    pytest_args = config.get("pytest_args", "-v --tb=long")
    # Two independent timeout knobs (design §3 D3):
    #   wall_timeout — absolute ceiling on the batch (legacy field name "timeout")
    #   idle_timeout — kill if log file shows no activity for this long
    # Either condition triggers SIGKILL + exit 124 inside the remote watchdog.
    wall_timeout = config.get("timeout", 600)
    idle_timeout = config.get("pytest_idle_timeout", 120)
    remote_log_dir = config.get(
        "remote_log_dir", "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"
    )

    # New filename (design §4 D5): pytest_<batch_id>.log replaces raw_log.txt.
    # The ``remote_log.raw_log_path`` field in batch_results.json keeps its
    # name so downstream consumers (failure-handler, analyze_failures) stay
    # source-compatible — only the filename on disk changes.
    raw_log_path = f"{remote_log_dir}/{batch_id}/pytest_{batch_id}.log"
    test_paths = " ".join(test_nodes)

    # Build the pytest invocation that the watchdog will background.
    # NOTE: redirection lives in the watchdog template (it owns the log path),
    # so this command does NOT include "> ... 2>&1".
    pytest_inner_cmd = (
        f"cd /gpfs/gcsp/M2.7_verify/vllm && "
        f"python3 -m pytest {test_paths} {pytest_args}"
    )

    watchdog_script = _build_watchdog_script(
        log_path=raw_log_path,
        pytest_full_cmd=pytest_inner_cmd,
        idle_timeout=idle_timeout,
        wall_timeout=wall_timeout,
    )

    # Wrap with `sudo -n docker exec ... bash -c "echo <b64> | base64 -d | bash"`
    # — fully quote-/newline-safe (see _wrap_with_docker_exec_b64 docstring +
    # post-mortem for run ut-20260623-223710).
    pytest_docker_cmd = _wrap_with_docker_exec_b64(
        docker_container, watchdog_script
    )

    started_at = _utc_now_iso_z()
    print(
        f"[INFO] Executing {len(tests)} tests remotely → {raw_log_path} "
        f"(idle={idle_timeout}s, wall={wall_timeout}s)"
    )

    # Local subprocess ceiling = wall_timeout + 60s (absolute backstop in case
    # the remote watchdog itself misbehaves; design §8 #2).
    try:
        pytest_res = run_remote(
            pytest_docker_cmd, timeout=wall_timeout, profile=remote_server
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

    # Second remote call: extract a summary via grep+tail on the pytest log.
    # Same b64 wrapping (single-line cmd but consistency + safety) and same
    # `sudo -n` so a NOPASSWD misconfig fails loud instead of hanging.
    summary_extract_cmd = _wrap_with_docker_exec_b64(
        docker_container,
        f"grep -E '(PASSED|FAILED|ERROR|SKIPPED|__WATCHDOG__)' {raw_log_path} ; "
        f"echo '----'; tail -50 {raw_log_path}",
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
        status, error_type = _classify_for_test(summary_text, _node(t))
        counters[status] = counters.get(status, 0) + 1
        test_entries.append({
            "id": t.get("id"),
            "test_node": _node(t),
            "status": status,
            "error_type": error_type,
            "duration_ms": 0,
        })

    batch_results = {
        "batch_id": batch_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "timeout": wall_timeout,
        "pytest_idle_timeout": idle_timeout,
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
    # Type-B fabrication backstop: validate payload BEFORE writing to disk.
    # If the executor itself drifts (or a future LLM substitute hand-writes
    # this file), fail loud here rather than letting manifest-updater consume
    # a malformed payload.
    _validate_batch_results_or_raise(batch_results)
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
