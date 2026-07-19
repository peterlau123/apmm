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

NOTE: PYTHONPATH must be cleared before importing any project modules to avoid
Hermes venv leaking into apmm subprocesses (fake 'jsonschema not installed').
"""

import os
# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

import base64
import functools
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover — jsonschema is a hard runtime dep but
    jsonschema = None  # tests may patch / install on demand

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.ut_common import get_paths, get_config  # noqa: E402
from skills.ut.ut_common.workflow_state_manager import (
    update_batch_running,
    update_batch_completed,
    load_workflow_state as load_state_for_check
)  # noqa: E402

_SCRIPT_DIR = Path(__file__).resolve().parent


# Shared bastion-disconnect detector (see skills/ut/ut_common/bastion_signals.py).
# Used by run_remote below to raise ConnectionError on transient outages.
from skills.ut.ut_common.bastion_signals import is_disconnect_blob  # noqa: E402

# ── Schema (Type-B fabrication backstop) ──────────────────────────────────────
#
# We enforce that batch_results.json is shape-correct BEFORE writing it, so a
# bug in this executor (or a future hand-rolled LLM substitute) cannot silently
# emit drifted / fabricated payloads that look plausible but are wrong-schema.
# The canonical schema lives next to this file.
_SCHEMA_PATH = _SCRIPT_DIR.parent / "batch_results_schema.json"


@functools.lru_cache(maxsize=1)
def _load_schema():
    """Read the canonical batch_results_schema.json. Cached on first call.

    Cached for the lifetime of the Python process: the schema is shipped with
    the SKILL and never edited mid-run; the validator may be called hundreds of
    times per workflow loop.
    """
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


# Sentinel used by the summary-extract command to ship the real remote pytest
# log size (`stat -c %s`) back to the executor without an extra RTT.
_REMOTE_LOG_SIZE_RE = re.compile(r"^__REMOTE_LOG_SIZE__(\d+)\s*$", re.MULTILINE)

# Defensive backstop for Bug A (design §9): if the __REMOTE_LOG_SIZE__ sentinel
# ever lands GLUED onto the XML tail (no separating newline — e.g. an older
# fetch path or a daemon that strips the interjected `echo` newline),
# _split_remote_log_size's line-anchored regex can't peel it off and the
# residue corrupts ET.fromstring. Strip any trailing sentinel residue right
# before parsing so a real passed/failed XML still resolves correctly.
_REMOTE_LOG_SIZE_RESIDUE_RE = re.compile(r"__REMOTE_LOG_SIZE__\d+\s*$")


def _split_remote_log_size(stdout: str) -> tuple[str, int | None]:
    """Extract the __REMOTE_LOG_SIZE__N sentinel from the summary stdout.

    Returns (summary_text_without_sentinel, size_bytes_or_None). When the
    sentinel is absent or unparseable, returns the original stdout and None.

    Picks the LAST sentinel match in the stream (not the first): the
    summary-extract command appends ``echo __REMOTE_LOG_SIZE__$(stat ...)``
    AFTER the grep/tail output, so the truthful sentinel is always the
    trailing one. A stray earlier line that happens to match the pattern
    (e.g. captured in pytest stdout) would otherwise hijack the recorded
    ``size_bytes`` and silently break the P1 audit.
    """
    if not stdout:
        return stdout, None
    matches = list(_REMOTE_LOG_SIZE_RE.finditer(stdout))
    if not matches:
        return stdout, None
    try:
        size = int(matches[-1].group(1))
    except ValueError:
        return stdout, None
    cleaned = _REMOTE_LOG_SIZE_RE.sub("", stdout).rstrip("\n")
    # `stat` returns 0 only when the file is missing (we OR'd `echo 0`); treat
    # 0 as "unknown" so it doesn't get recorded as a literal 0-byte size_bytes.
    # A genuinely 0-byte remote log is rare (pytest aborted pre-open); when
    # it happens we record size_bytes=None and P1's "exists & non-empty" rung
    # catches it.
    if size == 0:
        return cleaned, None
    return cleaned, size

# BastionManager is imported lazily at the call site so tests can patch it
# on this module before instantiation. Use importlib for hyphenated path.
import importlib.util
try:
    _bm_path = _project_root / "skills" / "ut" / "ut_common" / "scripts" / "bastion_manager.py"
    _bm_spec = importlib.util.spec_from_file_location("bastion_manager", _bm_path)
    _bm_mod = importlib.util.module_from_spec(_bm_spec)
    _bm_spec.loader.exec_module(_bm_mod)
    BastionManager = _bm_mod.BastionManager  # noqa: F401
except Exception:  # pragma: no cover - tests patch it directly
    BastionManager = None  # type: ignore[assignment]


# ── Watchdog template (per-test, wall-only — design §4.3, §4.5) ───────────────
#
# Per-test wall-clock watchdog (no idle/mtime heuristic — G2 deleted; design
# §4.5). One docker exec runs ONE test node with its own watchdog; a hang kills
# only this test (no batch-level collateral — G1/G8).
#
# Simplified watchdog: no process group management, no timeout loop.
# Timeout is managed by outer run_remote(timeout=wall_timeout).
# Zombie cleanup handled by GPU zombie cleaner at batch startup (§4.1).
#
# Notes on shell-quoting choices:
#   - The script is wrapped in `bash -c '<...>'` by the caller, so it must
#     not contain ANY ASCII single quotes (`'`).
#   - All shell variables are resolved at RUNTIME on the remote host.
#   - `--junit-xml=<path>` (built into pytest_full_cmd by the caller) makes
#     pytest the source of truth for per-test status; XML missing after a
#     SIGKILL = timeout signal (parsed by _parse_junit).
WATCHDOG_TEMPLATE = (
    "mkdir -p $(dirname {log_path}) && "
    "bash -c \"{pytest_full_cmd}\" > {log_path} 2>&1"
)


def _build_watchdog_script(
    *, log_path: str, pytest_full_cmd: str,
) -> str:
    """Render the per-test remote bash script.

    Simplified version (no watchdog loop, no process group management):
    - Synchronous execution of pytest
    - Timeout managed by outer run_remote(timeout=wall_timeout)
    - Zombie cleanup handled by GPU zombie cleaner at batch startup (§4.1)

    Raises ValueError if log_path or pytest_full_cmd contains single quotes
    (would break the outer ``bash -c '<...>'`` wrapper).

    Public for unit tests (see test_execute_batch_watchdog.py).
    """
    if "'" in pytest_full_cmd:
        raise ValueError(
            f"pytest_full_cmd contains single quote (breaks bash -c wrapper): {pytest_full_cmd!r}"
        )
    if "'" in log_path:
        raise ValueError(
            f"log_path contains single quote (breaks bash -c wrapper): {log_path!r}"
        )
    return WATCHDOG_TEMPLATE.format(
        log_path=log_path,
        pytest_full_cmd=pytest_full_cmd,
    )


def _wrap_with_docker_exec_b64(
    docker_container: str, inner_script: str, env_vars: dict | None = None
) -> str:
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

    env_vars: optional dict of environment variables to inject into the
        container via `-e VAR=VALUE` flags. Values are NOT shell-escaped
        (docker exec handles them as literal strings). Values CANNOT contain
        spaces or shell metacharacters ($, ;, |, ', ") — rejected with ValueError.
    """
    # Validate env_vars for shell-safe values (defense against injection).
    # Docker exec -e VAR=VALUE treats the value as a literal string, but
    # the `-e VAR=VALUE` fragment goes through shell parsing on the bastion
    # side before reaching docker. Spaces/metacharacters could break the
    # command structure.
    if env_vars:
        for key, value in env_vars.items():
            if ' ' in str(value) or any(c in str(value) for c in '$;|\'"'):
                raise ValueError(
                    f"env value cannot contain spaces or shell metacharacters: "
                    f"{key}={value}"
                )

    # Build -e flags from env_vars (if provided)
    env_flags = ""
    if env_vars:
        for key, value in env_vars.items():
            env_flags += f" -e {key}={value}"

    encoded = base64.b64encode(inner_script.encode("utf-8")).decode("ascii")
    # Outer quoting uses double quotes around a pure-ASCII payload (echo +
    # pipe + base64 chars). No single quotes, no newlines, no shell meta in
    # the encoded chunk → no quoting risk in any hop.
    return (
        f"sudo -n docker exec{env_flags} {docker_container} bash -c "
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

    # Heuristic: agent.py / bastion daemon connection failures — see
    # skills/ut/ut_common/bastion_signals.py for the token list (single source
    # of truth shared with manifest-updater's _stat_remote_log).
    if r.returncode != 0 and is_disconnect_blob(stdout + "\n" + stderr):
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


# ── JUnit XML parsing (per-test source of truth — design §4.4) ────────────────
#
# pytest is the source of truth for per-test status/duration/traceback; we no
# longer grep PASSED/FAILED out of human-readable output (G3/G5/G9). Each test
# node runs in its own docker exec with --junit-xml=<result_<node>.xml>; this
# parses that XML into a batch_results test entry.
#
# Status mapping (design §4.4):
#   <testcase> no children      → passed
#   <failure>                   → failed / error_type=assertion (or oom if msg says so)
#   <error>                     → error  / error_type=collection (or oom if msg says so)
#   XML missing / unparseable   → ignored / timeout
#       (watchdog SIGKILL before pytest flushes → the XML never lands on disk;
#        this is the per-test-model precise signal for G4, replacing the old
#        "killed test falls into error/other" misclassification.)

# Tokens that, when present in a <failure>/<error> message, reclassify the
# error_type to oom (retriable). Case-insensitive substring match.
_OOM_TOKENS = ("out of memory", "oom", "cuda error", "outofmemory")


def _error_type_from_message(message: str) -> str | None:
    """Map a JUnit failure/error message to an error_type, or None.

    Currently only detects OOM (retriable). Everything else keeps the default
    (assertion for <failure>, collection for <error>).
    """
    if not message:
        return None
    low = message.lower()
    if any(tok in low for tok in _OOM_TOKENS):
        return "oom"
    return None


def _parse_junit(xml_text: str, *, exit_code: int, node: str) -> dict:
    """Parse a single-test JUnit XML into a batch_results test-entry dict.

    Args:
        xml_text: raw XML fetched from the remote result_<node>.xml (may carry
            a trailing newline artifact from the daemon run path; rstripped).
        exit_code: the docker exec exit code for this test node (passed through
            to the entry; 124 = watchdog wall exceeded).
        node: test node id, for diagnostics only.

    Returns:
        dict with keys: status, error_type, error_message, duration_ms,
        exit_code — ready to merge into a tests[] entry.
    """
    # Timeout / missing-XML path: watchdog SIGKILL'd pytest before it flushed
    # the XML, OR the cat fetched nothing. This is the precise "test hung /
    # was killed" signal (design §4.4, G4).
    if not xml_text or not xml_text.strip():
        return {
            "status": "ignored",
            "error_type": "timeout",
            "error_message": "JUnit XML missing (watchdog SIGKILL or fetch empty)",
            "duration_ms": None,
            "exit_code": exit_code,
            "dependency_classification": {
                "status": "pending",
                "executor_signal": "timeout_no_xml",
                "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
            },
        }

    cleaned = _REMOTE_LOG_SIZE_RESIDUE_RE.sub("", xml_text).rstrip("\r\n")
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        return {
            "status": "ignored",
            "error_type": "timeout",
            "error_message": "JUnit XML unparseable (watchdog SIGKILL mid-flush?)",
            "duration_ms": None,
            "exit_code": exit_code,
            "dependency_classification": {
                "status": "pending",
                "executor_signal": "timeout_unparseable_xml",
                "executor_evidence": "JUnit XML unparseable (ET.ParseError)"
            },
        }

    testcase = root.find(".//testcase")
    if testcase is None:
        # Valid XML but no <testcase> — pytest aborted before writing results.
        return {
            "status": "ignored",
            "error_type": "timeout",
            "error_message": "JUnit XML has no <testcase> (pytest aborted pre-result)",
            "duration_ms": None,
            "exit_code": exit_code,
            "dependency_classification": {
                "status": "pending",
                "executor_signal": "timeout_no_testcase",
                "executor_evidence": "JUnit XML has no testcase element"
            },
        }

    # per-test duration (G6): <testcase time="0.123"> → ms.
    duration_ms = None
    time_attr = testcase.get("time")
    if time_attr:
        try:
            duration_ms = round(float(time_attr) * 1000)
        except ValueError:
            duration_ms = None

    failure = testcase.find("failure")
    error = testcase.find("error")

    if failure is not None:
        message = failure.get("message") or failure.text or ""
        error_type = _error_type_from_message(message) or "assertion"
        return {
            "status": "failed",
            "error_type": error_type,
            "error_message": message[:500] if message else None,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
        }

    if error is not None:
        message = error.get("message") or error.text or ""
        error_type = _error_type_from_message(message) or "collection"
        return {
            "status": "error",
            "error_type": error_type,
            "error_message": message[:500] if message else None,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
        }

    # No <failure>/<error> child → passed.
    return {
        "status": "passed",
        "error_type": None,
        "error_message": None,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
    }


# ── Batch-level log aggregation (Bug B fix — design §9) ───────────────────────
#
# remote_log.raw_log_path points at the batch-level pytest_<batch_id>.log, but
# v6's per-test watchdogs only write per-node logs (pytest_<batch_id>_<slug>.log).
# The P1 audit (update_test_load.audit_batch_results) independently `stat`s
# raw_log_path and rejects the batch if it's missing/empty — so a phantom batch
# path makes every genuinely-passing batch un-consumable. We materialize the
# batch log by concatenating the per-node logs (in input order) and stat it for
# size_bytes, making raw_log_path a real file whose size matches the audit.

def _aggregate_batch_log(
    *, node_logs: list[str], batch_log_path: str, container: str, profile: str,
) -> int | None:
    """Concatenate per-node logs into the batch-level log; return its real size.

    Returns the real byte size (>0), or None on disconnect / unparseable stat /
    empty result. None → size_bytes recorded as null; P1's "exists & non-empty"
    rung then catches a genuinely empty aggregation (e.g. all nodes crashed
    pre-write).
    """
    # cat the per-node logs (input order) into the batch log, then stat it.
    # /dev/null fallback when no node log survived so the batch file is at
    # least created (empty) rather than absent — P1 flags the empty case.
    targets = " ".join(node_logs) if node_logs else "/dev/null"
    inner = (
        f"mkdir -p $(dirname {batch_log_path}); "
        f"cat {targets} > {batch_log_path} 2>/dev/null; "
        f"stat -c %s {batch_log_path} 2>/dev/null || echo 0"
    )
    cmd = _wrap_with_docker_exec_b64(container, inner)
    try:
        res = run_remote(cmd, timeout=60, profile=profile)
    except ConnectionError:
        return None
    out = (res.get("stdout", "") or "").strip()
    m = re.match(r"^\s*(\d+)\s*$", out)
    if not m:
        return None
    size = int(m.group(1))
    return size if size > 0 else None


# ── GPU detection + zombie cleanup (design §4.1) ─────────────────────────────
#
# Dynamically detect free GPUs at batch start. A GPU is "free" iff its
# utilization is below the threshold AND (if occupied) the only occupants are
# our own pytest/watchdog zombies — which we clean up. Cards with foreign
# processes, or mixed (ours + foreign), are excluded entirely (we don't dare
# kill only our own on a mixed card — simple and safe).
#
# Zombie identification is by `ps` cmd match + etime, NOT process-tree walk:
# orphaned workers started under `setsid` get re-parented to init (PPID=1), so
# a PPID-chain walk can't trace them back to the original batch (design §4.1).

# cmd tokens that mark a process as "ours" (pytest / the watchdog wrapper).
_OWN_CMD_TOKENS = ("pytest", "python3 -m pytest", "watchdog")

# GPU utilization threshold (%) — cards at/above this are "occupied".
# v1 coarse filter (design §2, §8).
_GPU_USAGE_THRESHOLD_PCT = 50


def _detect_free_gpus(
    *, container: str, profile: str,
    threshold_pct: int = _GPU_USAGE_THRESHOLD_PCT,
) -> tuple[list[int], int | None]:
    """Detect free GPU ids inside the container, cleaning up our own zombies.

    Returns (free_ids, fallback_min_usage_card):
      free_ids — GPU indices safe to pin (released-clean or never-occupied).
      fallback_min_usage_card — the lowest-usage card id (for 0-card D1
        degradation); None if detection failed entirely.

    On any detection failure (nvidia-smi missing, parse error), returns
    ([], None) so the caller falls through to D1 with no card hint.
    """
    # One docker exec: dump per-GPU memory + compute-apps in a parseable form.
    # `nvidia-smi` is invoked WITHOUT sudo (container already has GPU access).
    inner = (
        "nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu "
        "--format=csv,noheader,nounits 2>/dev/null; "
        "echo __APPS__; "
        "nvidia-smi --query-compute-apps=pid,used_memory,gpu_uuid "
        "--format=csv,noheader,nounits 2>/dev/null; "
        "echo __UUIDS__; "
        "nvidia-smi --query-gpu=index,gpu_uuid --format=csv,noheader,nounits 2>/dev/null"
    )
    cmd = _wrap_with_docker_exec_b64(container, inner)
    try:
        res = run_remote(cmd, timeout=40, profile=profile)
    except ConnectionError:
        raise
    out = res.get("stdout", "") or ""
    if res.get("exit_code", 0) != 0 and not out:
        return [], None

    # Split the three sections.
    gpu_lines, app_lines, uuid_lines = _split_gpu_sections(out)

    # index → gpu_uuid
    uuid_by_index: dict[int, str] = {}
    for ln in uuid_lines:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
            uuid_by_index[int(parts[0])] = parts[1]

    # index → {used, total, util}
    gpu_info: dict[int, dict] = {}
    for ln in gpu_lines:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 4:
            continue
        # Skip header line (contains non-numeric fields like "index", "name")
        if not parts[0].lstrip("-").isdigit():
            continue
        try:
            idx = int(parts[0])
            # Handle both: "0" (nounits) and "0 MiB" (with units)
            used_str = parts[1].split()[0] if parts[1] else "0"
            total_str = parts[2].split()[0] if parts[2] else "0"
            util_str = parts[3].split()[0] if parts[3] else "0"
            used = int(used_str)
            total = int(total_str)
            util = int(util_str)
        except ValueError:
            continue
        gpu_info[idx] = {"used": used, "total": total, "util": util}

    if not gpu_info:
        return [], None

    # gpu_uuid → list of pids occupying it
    pids_by_uuid: dict[str, list[int]] = {}
    for ln in app_lines:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
            pid = int(parts[0])
            uuid = parts[1]
            pids_by_uuid.setdefault(uuid, []).append(pid)

    free_ids: list[int] = []
    for idx, info in sorted(gpu_info.items()):
        used = info["used"]
        total = info["total"]
        util = info["util"]
        # Free filter: memory usage ratio below threshold.
        # ponytail: was `util < threshold_pct` (compute util), which mis-flagged
        # a card holding 86% VRAM at 0% util as "free" -> OOM on pin. Use VRAM ratio.
        mem_ratio_pct = (used / total * 100) if total > 0 else 100
        if mem_ratio_pct < threshold_pct:
            free_ids.append(idx)
            continue
        # Occupied above threshold — inspect occupants to decide zombie cleanup.
        uuid = uuid_by_index.get(idx, "")
        pids = pids_by_uuid.get(uuid, [])
        if not pids:
            # High util but no tracked compute-apps (transient/other subsys);
            # treat as occupied, exclude.
            continue
        classification = _classify_card_occupants(pids, container=container,
                                                  profile=profile)
        if classification == "own_zombie":
            # Pure our-own zombie(s) → clean up, re-check memory release.
            if _cleanup_zombies(pids, container=container, profile=profile):
                free_ids.append(idx)
            # else: didn't release → stays excluded
        # "foreign" or "mixed" → excluded (do not kill)

    # Fallback card for 0-free D1: lowest memory.used.
    fallback = None
    if gpu_info:
        fallback = min(gpu_info, key=lambda i: gpu_info[i]["used"])

    return free_ids, fallback


def _split_gpu_sections(out: str) -> tuple[list[str], list[str], list[str]]:
    """Split the 3-section nvidia-smi dump into (gpu_lines, app_lines, uuid_lines)."""
    # out may carry the trailing-LF artifact + the echo'd section markers.
    sections = out.replace("\r", "").split("__APPS__")
    gpu_part = sections[0] if sections else ""
    rest = sections[1].split("__UUIDS__") if len(sections) > 1 else ["", ""]
    app_part = rest[0]
    uuid_part = rest[1] if len(rest) > 1 else ""

    def _lines(s: str) -> list[str]:
        return [ln.strip() for ln in s.splitlines() if ln.strip()]

    return _lines(gpu_part), _lines(app_part), _lines(uuid_part)


def _classify_card_occupants(
    pids: list[int], *, container: str, profile: str,
) -> str:
    """Classify the occupants of one GPU card.

    Returns one of:
      "own_zombie" — every occupant matches our pytest/watchdog cmd tokens.
      "foreign"    — no occupant matches (someone else's processes).
      "mixed"      — some ours, some foreign (excluded; don't kill).
    """
    own = 0
    foreign = 0
    for pid in pids:
        if _is_own_process(pid, container=container, profile=profile):
            own += 1
        else:
            foreign += 1
    if own and not foreign:
        return "own_zombie"
    if foreign and not own:
        return "foreign"
    return "mixed"


def _is_own_process(pid: int, *, container: str, profile: str) -> bool:
    """True if `pid` (inside the container) looks like our pytest/watchdog.

    Uses `ps -o pid,ppid,etime,cmd -p <pid>` cmd match (design §4.1). On any
    ps failure (pid already gone), returns False (can't confirm → treat as
    foreign → card excluded, the safe choice).
    """
    if pid <= 0:
        return False
    inner = f"ps -o pid,etime,cmd -p {pid} 2>/dev/null || true"
    cmd = _wrap_with_docker_exec_b64(container, inner)
    try:
        res = run_remote(cmd, timeout=15, profile=profile)
    except ConnectionError:
        return False
    out = res.get("stdout", "") or ""
    low = out.lower()
    return any(tok in low for tok in _OWN_CMD_TOKENS)


def _cleanup_zombies(
    pids: list[int], *, container: str, profile: str,
    sigterm_grace_s: int = 5, verify_attempts: int = 3, verify_interval_s: int = 2,
) -> bool:
    """SIGTERM → grace → SIGKILL our own zombie PIDs, then verify GPU mem release.

    Returns True iff memory freed (card reusable). EPERM (different UID) →
    returns False (we can't kill it → exclude the card). The verify step
    polls nvidia-smi a few times because CUDA memory release lags SIGKILL
    (design §4.1 step 3).
    """
    # SIGTERM first.
    _kill_pids(pids, signal_name="TERM", container=container, profile=profile)
    if _pids_alive(pids, container=container, profile=profile,
                   grace_s=sigterm_grace_s):
        # Still alive after grace → SIGKILL -9.
        _kill_pids(pids, signal_name="KILL", container=container, profile=profile)

    # Verify memory release by re-querying the card's memory.used. We don't have
    # the card index here, so verify by the pid set being gone AND no new
    # compute-app on the same uuid — simpler: re-check the pids are dead and
    # trust nvidia-smi compute-apps no longer lists them.
    for _ in range(verify_attempts):
        if not _pids_alive(pids, container=container, profile=profile,
                           grace_s=0):
            return True
        # wait and retry
        _sleep_blocking(verify_interval_s)
    return False


def _kill_pids(pids: list[int], *, signal_name: str, container: str, profile: str) -> None:
    """Send a signal to each pid inside the container (best-effort)."""
    if not pids:
        return
    pid_args = " ".join(str(p) for p in pids)
    inner = f"kill -{signal_name} {pid_args} 2>/dev/null || true"
    cmd = _wrap_with_docker_exec_b64(container, inner)
    try:
        run_remote(cmd, timeout=15, profile=profile)
    except ConnectionError:
        pass


def _pids_alive(pids: list[int], *, container: str, profile: str, grace_s: int) -> bool:
    """True if any of `pids` is still alive in the container.

    `grace_s` > 0 blocks for that long before checking (SIGTERM grace window).
    """
    if not pids:
        return False
    if grace_s > 0:
        _sleep_blocking(grace_s)
    pid_args = " ".join(str(p) for p in pids)
    # `kill -0` is a no-op signal to test liveness; exit 0 = alive.
    inner = (
        f"for p in {pid_args}; do "
        "if kill -0 $p 2>/dev/null; then echo ALIVE; exit 0; fi; "
        "done; echo DEAD"
    )
    cmd = _wrap_with_docker_exec_b64(container, inner)
    try:
        res = run_remote(cmd, timeout=15, profile=profile)
    except ConnectionError:
        return True  # assume alive (conservative — don't reuse the card)
    return "ALIVE" in (res.get("stdout", "") or "")


def _sleep_blocking(seconds: int) -> None:
    """Block for `seconds` (subprocess-safe; used for SIGTERM grace / verify)."""
    import time as _time
    _time.sleep(seconds)


# ── Main entry ────────────────────────────────────────────────────────────────

def execute_batch(batch_config_path: Path, workflow_state_path: Path, *, exec_config: dict | None = None) -> dict:
    """Execute a batch of tests remotely in PARALLEL; return a summary dict.

    v6 parallel design (2026-06-24-executor-parallel-gpu.md §4): each test_node
    runs in its own docker exec with its own per-test wall watchdog, pinned to
    a free GPU via CUDA_VISIBLE_DEVICES. pytest --junit-xml is the source of
    truth for per-test status; we parse the XML locally (no grep of human
    output). A hang kills only that test (no batch-level collateral).

    Side effects on success:
      - writes <batch_dir>/batch_results.json
      - writes <batch_dir>/summary.txt (aggregated per-test outcomes)

    On Bastion disconnect: writes neither; returns {"next_action": "wait", ...}.
    """
    batch_config_path = Path(batch_config_path)
    workflow_state_path = Path(workflow_state_path)

    batch_config = json.loads(batch_config_path.read_text(encoding="utf-8"))
    config = exec_config if exec_config is not None else get_config(workflow_state_path)

    batch_dir = batch_config_path.parent
    batch_id = batch_config["batch_id"]
    tests = batch_config["tests"]
    batch_type = batch_config.get("batch_type", "normal")
    gpu_per_test = batch_config.get("gpu_per_test", 1)

    remote_server = config.get("remote_server", "t_h20")
    docker_container = config.get("docker_container", "v0.13.0_torch2.5.1_compile")
    pytest_args = config.get("pytest_args", "-v --tb=long")
    # per-test wall budget (design §2 v1 = 300s). Legacy config key "timeout"
    # is reused but now means PER-TEST, not batch-total.
    wall_timeout = config.get("timeout", 300)
    remote_log_dir = config.get(
        "remote_log_dir", "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"
    )
    # Container environment variables (HF offline, cache paths etc.)
    # Source: workflow.yaml config.container_env (NOT workflow_state.json)
    # Note: CUDA_VISIBLE_DEVICES is excluded here and set per-test in pytest_full_cmd
    import yaml
    # When exec_config is provided (unit tests), skip reading workflow_state.json
    if exec_config is not None:
        container_env_raw = {}
    else:
        state_raw = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        workflow_yaml_str = state_raw.get("paths", {}).get("workflow_yaml", "")
        workflow_yaml_path = Path(workflow_yaml_str) if workflow_yaml_str else None
        if workflow_yaml_path and workflow_yaml_path.is_file():
            wf = yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
            container_env_raw = wf.get("config", {}).get("container_env", {})
        else:
            container_env_raw = {}
    # Exclude CUDA_VISIBLE_DEVICES (per-test GPU assignment overrides global config)
    container_env = {
        k: v for k, v in container_env_raw.items()
        if k != "CUDA_VISIBLE_DEVICES"
    }

    # Batch-level log dir (per-node log/xml live here too, named with the node).
    batch_log_dir = f"{remote_log_dir}/{batch_id}"
    raw_log_path = f"{batch_log_dir}/pytest_{batch_id}.log"  # batch-level pointer

    # ── GPU detection + zombie cleanup (design §4.1) ────────────────────────
    # Force GPU mode: if detection fails repeatedly, use all 8 GPUs
    # Read directly from workflow.yaml config
    wf_config = wf.get("config", {}) if 'wf' in dir() and wf else {}
    force_gpu_count = wf_config.get("force_gpu_count", config.get("force_gpu_count", 0))
    
    if force_gpu_count > 0:
        # Force mode: bypass detection, use specified GPU count
        gpu_pool = list(range(force_gpu_count))
        print(f"[INFO] Force GPU mode: using {gpu_pool} (parallelism={len(gpu_pool)})")
    else:
        try:
            free_ids, fallback_card = _detect_free_gpus(
                container=docker_container, profile=remote_server,
            )
        except ConnectionError as e:
            return _disconnect_wait(batch_id, remote_server, workflow_state_path, str(e))

        if free_ids:
            gpu_pool = free_ids
            print(f"[INFO] Free GPUs detected: {gpu_pool} (parallelism={len(gpu_pool)})")
        else:
            # 0-card D1 degradation (design §4.2): serialize on the lowest-usage
            # card. If even fallback is None (detection failed), still try card 0.
            gpu_pool = [fallback_card if fallback_card is not None else 0]
            print(f"[WARN] 0 free GPU — D1 degrade: serialize on card {gpu_pool[0]}")

    if batch_type == "distributed":
        n_workers = len(gpu_pool) // gpu_per_test
        print(f"[INFO] Distributed mode: {n_workers} parallel tests, {gpu_per_test} GPUs each")
    else:
        n_workers = len(gpu_pool)

    started_at = _utc_now_iso_z()

    # ── 更新 workflow_state.json 为 'running' 状态（两阶段更新）──────
    try:
        update_batch_running(
            workflow_state_path=workflow_state_path,
            batch_id=batch_id,
            gpu_pool=gpu_pool,
            started_at=started_at
        )
    except Exception as e:
        print(f"[WARN] Failed to update workflow_state to running: {e}")

    print(
        f"[INFO] Executing {len(tests)} tests in parallel ({n_workers} workers) "
        f"→ {batch_log_dir}/ (per-test wall={wall_timeout}s)"
    )

    # ── Per-test parallel dispatch (design §4.2/§4.3) ───────────────────────
    # Each task: pin a GPU, run one node under its own watchdog, fetch its
    # JUnit XML, parse it. ThreadPoolExecutor because each task blocks on a
    # remote subprocess (run_remote) — true parallelism across the SSH daemon.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _node_slug(node: str) -> str:
        """Stable, filesystem-safe slug for per-node log/xml filenames."""
        return re.sub(r"[^A-Za-z0-9_]+", "_", node).strip("_") or "node"

    def _run_one_test(idx: int, test: dict) -> dict:
        node = _node(test)
        slug = _node_slug(node)
        gpu_id = gpu_pool[idx % n_workers]
        node_log = f"{batch_log_dir}/pytest_{batch_id}_{slug}.log"
        node_xml = f"{batch_log_dir}/result_{batch_id}_{slug}.xml"

# pytest invocation for ONE node. --junit-xml is the result source of
        # truth; -o junit_logging=out-err (pytest 9 has no --junit-logging CLI
        # flag — §6.2 实测偏差). Redirection lives in the watchdog template.
        # NOTE: agent.py now uses base64 encoding to protect brackets [] and all
        # special characters. No need to escape or use -k workaround here.
        if batch_type == "distributed":
            # Distributed: allocate gpu_per_test contiguous GPUs
            gpu_start = (idx % n_workers) * gpu_per_test
            gpu_ids = ",".join(str(gpu_pool[gpu_start + g]) for g in range(gpu_per_test))
            pytest_full_cmd = (
                f"cd /gpfs/gcsp/M2.7_verify/vllm && "
                f"CUDA_VISIBLE_DEVICES={gpu_ids} torchrun --nproc_per_node={gpu_per_test} "
                f"-m pytest {node} --junit-xml={node_xml} {pytest_args} -o junit_logging=out-err"
            )
        else:
            # Normal: single GPU per test
            pytest_full_cmd = (
                f"cd /gpfs/gcsp/M2.7_verify/vllm && "
                f"CUDA_VISIBLE_DEVICES={gpu_id} python3 -m pytest {node} "
                f"--junit-xml={node_xml} {pytest_args} -o junit_logging=out-err"
            )
        watchdog_script = _build_watchdog_script(
            log_path=node_log,
            pytest_full_cmd=pytest_full_cmd,
        )
        docker_cmd = _wrap_with_docker_exec_b64(
            docker_container, watchdog_script, env_vars=container_env
        )

        try:
            res = run_remote(docker_cmd, timeout=wall_timeout, profile=remote_server)
            exit_code = res.get("exit_code", 0)
        except ConnectionError:
            # Per-test disconnect: mark ignored; overall batch disconnect is
            # decided below from the aggregated _disconnected flag.
            return {
                "id": test.get("id"), "test_node": node,
                "status": "ignored", "error_type": "timeout",
                "error_message": "bastion disconnect during exec",
                "duration_ms": None, "exit_code": None,
                "gpu_id": gpu_id, "log_path": node_log, "xml_path": node_xml,
                "dependency_classification": {
                    "status": "pending",
                    "executor_signal": "disconnect_exec",
                    "executor_evidence": "bastion disconnect during test exec"
                },
                "_disconnected": True,
            }

        # Second remote call: fetch the JUnit XML + this node log size.
        # Bug A fix (design §9): JUnit XML is single-line with NO trailing
        # newline, so a bare `cat {node_xml}` runs its output straight into
        # the `echo __REMOTE_LOG_SIZE__...` sentinel on the SAME line. The
        # line-anchored sentinel regex then can't match, the glued tail
        # survives into ET.fromstring → "junk after document element", and a
        # genuinely-passed test gets misclassified as retriable_error/timeout.
        # A bare `echo` between them forces the sentinel onto its own line.
        fetch_cmd = _wrap_with_docker_exec_b64(
            docker_container,
            f"cat {node_xml} 2>/dev/null; "
            f"echo; "
            f"echo __REMOTE_LOG_SIZE__$(stat -c %s {node_log} 2>/dev/null || echo 0)",
            env_vars=container_env,
        )
        try:
            fetch_res = run_remote(fetch_cmd, timeout=60, profile=remote_server)
            fetch_stdout = fetch_res.get("stdout", "") or ""
        except ConnectionError:
            return {
                "id": test.get("id"), "test_node": node,
                "status": "ignored", "error_type": "timeout",
                "error_message": "bastion disconnect during xml fetch",
                "duration_ms": None, "exit_code": exit_code,
                "gpu_id": gpu_id, "log_path": node_log, "xml_path": node_xml,
                "dependency_classification": {
                    "status": "pending",
                    "executor_signal": "disconnect_xml_fetch",
                    "executor_evidence": "bastion disconnect during xml fetch"
                },
                "_disconnected": True,
            }

        # The cat output IS the XML (possibly with a trailing-LF artifact,
        # handled by _parse_junit rstrip). The __REMOTE_LOG_SIZE__ sentinel is
        # appended after the XML on the same stream — split it off so it does
        # not corrupt XML parsing. (Bug A: the `echo` in fetch_cmd guarantees
        # the sentinel lands on its own line; the per-node size it carries is
        # no longer used — the batch-level size_bytes comes from
        # _aggregate_batch_log after all nodes finish.)
        xml_text, _ = _split_remote_log_size(fetch_stdout)

        parsed = _parse_junit(xml_text, exit_code=exit_code, node=node)
        return {
            "id": test.get("id"),
            "test_node": node,
            "status": parsed["status"],
            "error_type": parsed["error_type"],
            "error_message": parsed["error_message"],
            "duration_ms": parsed["duration_ms"],
            "exit_code": parsed["exit_code"],
            "gpu_id": gpu_id,
            "log_path": node_log,
            "xml_path": node_xml,
        }

    # Dispatch concurrently. Preserve input order in the final entries.
    results_by_idx: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_idx = {
            pool.submit(_run_one_test, i, t): i for i, t in enumerate(tests)
        }
        for fut in as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                results_by_idx[i] = fut.result()
            except Exception as e:  # pragma: no cover — defensive
                node = _node(tests[i])
                results_by_idx[i] = {
                    "id": tests[i].get("id"), "test_node": node,
                    "status": "retriable_error", "error_type": "other",
                    "error_message": f"executor task crashed: {e}",
                    "duration_ms": None, "exit_code": None,
                    "gpu_id": gpu_pool[i % n_workers],
                    "log_path": None, "xml_path": None,
                }

    # If ANY task hit a bastion disconnect, treat the whole batch as
    # disconnected (wait policy) so the supervisor re-selects later. Partial
    # results across a disconnect are unreliable.
    if any(r.get("_disconnected") for r in results_by_idx.values()):
        return _disconnect_wait(
            batch_id, remote_server, workflow_state_path,
            "bastion disconnect during per-test exec/fetch",
        )

    # Bug B fix (design §9): materialize the batch-level log so
    # remote_log.raw_log_path points at a REAL file the P1 audit can stat.
    # v6's per-test watchdogs only wrote per-node logs; concatenate them (in
    # input order) into pytest_<batch_id>.log and stat it for size_bytes.
    node_logs_in_order = [
        results_by_idx[i]["log_path"]
        for i in range(len(tests))
        if results_by_idx[i].get("log_path")
    ]
    batch_log_size = _aggregate_batch_log(
        node_logs=node_logs_in_order,
        batch_log_path=raw_log_path,
        container=docker_container,
        profile=remote_server,
    )

    finished_at = _utc_now_iso_z()
    captured_at = finished_at

    # Build ordered test entries + summary text (aggregated per-test outcomes).
    test_entries = []
    summary_lines = []
    counters = {"passed": 0, "failed": 0, "error": 0, "skipped": 0,
                "retriable_error": 0, "ignored": 0}
    any_exit_nonzero = False
    for i in range(len(tests)):
        r = results_by_idx[i]
        status = r["status"]
        counters[status] = counters.get(status, 0) + 1
        if r.get("exit_code") not in (None, 0):
            any_exit_nonzero = True
        r.pop("_disconnected", None)
        test_entries.append({
            "id": r.get("id"),
            "test_node": r["test_node"],
            "status": r["status"],
            "error_type": r["error_type"],
            "error_message": r.get("error_message"),
            "duration_ms": r["duration_ms"],
            "exit_code": r["exit_code"],
            "gpu_id": r["gpu_id"],
            "log_path": r["log_path"],
            "xml_path": r["xml_path"],
        })
        summary_lines.append(
            f"{status.upper():14} {r['test_node']} "
            f"(gpu={r['gpu_id']}, {r['duration_ms']}ms, exit={r['exit_code']})"
        )

    summary_text = "\n".join(summary_lines) + "\n"
    summary_path = batch_dir / "summary.txt"
    summary_path.write_text(summary_text, encoding="utf-8")

    batch_results = {
        "batch_id": batch_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "timeout": wall_timeout,
        "exit_code": 1 if any_exit_nonzero else 0,
        "remote_log": {
            "host": remote_server,
            "container": docker_container,
            "raw_log_path": raw_log_path,
            "size_bytes": batch_log_size if batch_log_size else None,
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
            "ignored": counters.get("ignored", 0),
        },
    }

    output_path = batch_dir / "batch_results.json"
    # Type-B fabrication backstop: validate payload BEFORE writing to disk.
    try:
        _validate_batch_results_or_raise(batch_results)
    except (ValueError, RuntimeError) as e:
        rejected_path = batch_dir / "batch_results.rejected.json"
        try:
            rejected_path.write_text(
                json.dumps(batch_results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        reason = f"schema_validation_failed: {e}"
        print(f"[ERROR] {reason}; quarantined → {rejected_path}")
        return {
            "batch_id": batch_id,
            "next_action": "wait",
            "reason": reason,
            "rejected_path": str(rejected_path),
        }
    output_path.write_text(
        json.dumps(batch_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[OK] {output_path}")

    # ── 更新 workflow_state.json 为 'completed' 状态（两阶段更新）──────
    finished_at = _utc_now_iso_z()
    try:
        update_batch_completed(
            workflow_state_path=workflow_state_path,
            batch_id=batch_id,
            results_path=str(output_path),
            stats=batch_results["statistics"],
            completed_at=finished_at
        )

        # ── 强制输出状态检查（防止Agent批量自动化）────────────────
        print("=" * 60)
        print("STAGE COMPLETED: execute_batch")
        print(f"Batch ID: {batch_id}")
        print(f"Results: passed={batch_results['statistics']['passed']}, "
              f"failed={batch_results['statistics']['failed']}")
        print(f"GPU Pool: {gpu_pool}")

        # 检查 workflow_state.json 是否成功更新
        state = load_state_for_check(workflow_state_path)
        if batch_id in state.get("batches", {}):
            batch_state = state["batches"][batch_id]
            print(f"Workflow State Updated: {batch_state['status']}")
            print(f"Batch Stats: completed={state['batch_stats']['completed']}")
        else:
            print("[WARN] Workflow State NOT UPDATED!")

        print("NEXT ACTION: update_manifest or select_next_batch")
        print("=" * 60)
    except Exception as e:
        print(f"[WARN] Failed to update workflow_state to completed: {e}")

    return {
        "batch_id": batch_id,
        "batch_results_path": str(output_path),
        "stats": batch_results["statistics"],
    }


def _disconnect_wait(batch_id, remote_server, workflow_state_path, reason) -> dict:
    """Bastion disconnect: notify BastionManager, return the wait contract.

    Does NOT write batch_results.json, does NOT mutate manifest/test status
    (design: Stage 2 re-selects the batch later).
    """
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-config", required=True)
    parser.add_argument("--workflow-state", required=True)
    parser.add_argument("--batch-id", default=None, help="Batch identifier (for logging)")
    parser.add_argument("--timeout", type=int, default=None, help="Per-test wall-clock timeout (seconds)")
    args = parser.parse_args()

    exec_config = {}
    if args.timeout:
        exec_config["timeout"] = args.timeout
    result = execute_batch(Path(args.batch_config), Path(args.workflow_state), exec_config=exec_config or None)
    print(json.dumps(result, indent=2))
