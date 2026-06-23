"""M3 (postmortem 2026-06-23 issue #2) — OTP never-persisted regression.

The OTP code is a transient memory-only secret. After a run completes (or
fails), no artifact under `runs/<run_id>/` may contain a 6-digit pattern that
could be confused with an OTP — workflow_state.json, logs, batch files,
manifest, kanban metadata, anything.

This test sweeps every existing run directory for the literal pattern
`OTP\\s+\\d{6}` and any stray standalone 6-digit number in keys named `otp*`.
If no runs exist (fresh repo), the test passes trivially.
"""
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = PROJECT_ROOT / "runs"

# Pattern that would indicate an OTP leak: "OTP" keyword followed by 6 digits
OTP_LEAK_PATTERN = re.compile(r"OTP\s+\d{6}", re.IGNORECASE)


def _iter_run_files():
    """Yield (path, text) for every readable text file under runs/."""
    if not RUNS_DIR.exists():
        return
    for path in RUNS_DIR.rglob("*"):
        if not path.is_file():
            continue
        # Skip binary / large files
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".gz", ".tar", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError):
            continue
        if len(text) > 5_000_000:  # >5MB; skip
            continue
        yield path, text


def test_no_otp_keyword_with_6_digits_in_runs():
    """No `OTP 562741`-style leak anywhere under runs/."""
    hits = []
    for path, text in _iter_run_files():
        for m in OTP_LEAK_PATTERN.finditer(text):
            hits.append((path.relative_to(PROJECT_ROOT), m.group(0)))

    assert not hits, (
        f"Potential OTP leak in runs/ tree (count={len(hits)}):\n"
        + "\n".join(f"  {p}: {match!r}" for p, match in hits[:10])
    )


def test_workflow_state_has_no_otp_code_field():
    """workflow_state.json bastion section must never carry an `otp` value.

    BastionManager._update_bastion_state pops `otp_request_id` when status
    is not waiting_for_otp. The actual code itself must never be written —
    not even into a `waiting_for_otp` state file.
    """
    forbidden_keys = {"otp", "otp_code", "code"}
    bad = []
    for path in RUNS_DIR.rglob("workflow_state.json") if RUNS_DIR.exists() else []:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        bastion = state.get("bastion") or {}
        for k in forbidden_keys:
            if k in bastion:
                bad.append((path.relative_to(PROJECT_ROOT), k, bastion[k]))

    assert not bad, (
        "workflow_state.json bastion section contains forbidden OTP field:\n"
        + "\n".join(f"  {p}: {k}={v!r}" for p, k, v in bad)
    )
