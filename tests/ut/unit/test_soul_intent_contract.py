"""SOUL.md intent-classification contract tests.

The ut-supervisor Agent IS the LLM; intent rules live in SOUL.md (not code).
These tests guard the SOUL prompt against regressions introduced by issue #1
of the 2026-06-23 L4 postmortem:

  - Bare "跑 ut workflow" (no L-suffix / no 正式|生产|全量) MUST classify
    as `unknown`, NOT `start_production`.
  - The conservative guard ("NEVER classify as start_* with conf ≥ 0.7
    unless …") MUST stay in the prompt.

If a future edit reintroduces the contradiction, these tests fail loudly.

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §2
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOUL_PATH = PROJECT_ROOT / "tests" / "ut" / "integration" / "fixtures" / "profiles" / "ut-supervisor" / "SOUL.md"


@pytest.fixture(scope="module")
def soul_text() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


# ── Negative regression — the contradictory legacy rule MUST be gone ──────────


def test_bare_run_ut_workflow_not_mapped_to_start_production(soul_text):
    """The deleted line — must never come back.

    Original (removed in M1): '"跑 ut workflow" (no L-suffix) → start_production'.
    Conflicts with the conservative guard. Reintroducing it = the original bug.
    """
    forbidden_patterns = [
        '"跑 ut workflow" (no L-suffix)',
        '"跑 ut workflow"(no L-suffix)',
    ]
    for pat in forbidden_patterns:
        if pat in soul_text:
            window = soul_text[soul_text.index(pat):soul_text.index(pat) + 200]
            assert "start_production" not in window, (
                f"SOUL.md regressed: bare '{pat}' is again mapped to "
                f"start_production. See postmortem §2.3."
            )


# ── Positive — conservative guard + help-card path must be present ─────────────


def test_conservative_guard_still_in_soul(soul_text):
    """The 'NEVER classify as start_* unless tier name or 正式/生产/全量' guard."""
    assert "NEVER classify as `start_*`" in soul_text or \
           "NEVER classify as start_*" in soul_text, \
           "SOUL.md missing the conservative guard against accidental start_production."


def test_bare_run_ut_workflow_routes_to_unknown(soul_text):
    """The new rule: bare phrase → unknown → help card."""
    assert "跑 ut workflow" in soul_text
    idx = soul_text.find('Bare "跑 ut workflow"')
    assert idx >= 0, "SOUL.md missing the explicit Bare-phrase rule from postmortem §2.3."
    window = soul_text[idx:idx + 200]
    assert "unknown" in window, \
        f"Bare '跑 ut workflow' rule must route to `unknown`. Got: {window!r}"


def test_otp_secrecy_clause_still_present(soul_text):
    """Adjacent regression guard — OTP must never be logged.

    Issue #2 (M3) will rely on this clause; ensure M1's edits didn't disturb it.
    """
    assert "OTP" in soul_text
    lowered = soul_text.lower()
    assert "never print" in lowered or "never store" in lowered or \
           "never echo" in lowered, \
           "SOUL.md missing the OTP secrecy clause."
