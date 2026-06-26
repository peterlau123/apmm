"""bastion_signals.py — single source of truth for bastion-disconnect
heuristics.

When ``tools/agent.py`` is invoked against an unreachable bastion daemon (SSH
refusal, daemon down, route loss, ...), it exits non-zero with one of a small
set of recognisable phrases in stderr/stdout. Multiple call sites (Stage 3
executor's ``run_remote``, Stage 5 manifest-updater's ``_stat_remote_log``)
need to detect this case and map it to ``next_action=wait`` rather than
re-trying the same operation indefinitely or treating it as a structural
audit failure.

Centralising the token list here avoids the drift bug where a new disconnect
phrase is added to one caller and forgotten in the others.
"""
from __future__ import annotations

# Lowercase substrings that, when found in agent.py's combined stdout+stderr
# for a non-zero exit, mean "transient bastion outage; caller should wait".
# Keep entries lowercase; matcher lowercases the blob.
DISCONNECT_SIGNALS: tuple[str, ...] = (
    "daemon not reachable",
    "connection refused",
    "no route to host",
    "bastion disconnected",
    "ssh: connect to host",
)


def is_disconnect_blob(blob: str) -> bool:
    """Return True if ``blob`` (concatenated stdout+stderr) contains any
    known disconnect signal token. Caller is responsible for first ensuring
    this is a non-zero-exit context — every non-zero exit isn't necessarily
    a disconnect."""
    if not blob:
        return False
    low = blob.lower()
    return any(sig in low for sig in DISCONNECT_SIGNALS)
