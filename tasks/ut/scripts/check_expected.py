#!/usr/bin/env python3
"""
check_expected.py — Generic L1/L2/L3/L4 run-vs-expected comparator.

Reads a run's manifest.json (+ optional batch_results.json files) and an
expected-outcome JSON fixture (e.g. tests/ut/integration/fixtures/L4_expected.json),
evaluates every assertion section present in the expected file, and emits a
single JSON verdict to stdout (or to --output-card-json).

Sections handled (each optional — only evaluated if present in expected):
  - terminal_state_distribution        (all tiers)
  - anti_fabrication_assertions        (AF-1 / AF-2 / AF-3; L4-style)
  - stage_invariants                   (STG-1 / STG-2 / STG-3; L3+)
  - dependency_chain_invariants        (INV-1..5; L4 only — verified vs batch_results)
  - per_test                           (per-node trajectory hints; soft)

Exit codes:
  0 — overall PASS (all hard assertions hold)
  1 — overall FAIL (>=1 hard assertion failed)
  2 — expected file unparseable / structurally invalid

AF-1 requires `tools/agent.py -p <profile> run "stat -c %s <log_file>"` to
verify remote log files exist; the profile is read from the expected file's
metadata.bastion_profile (defaults to "t_h20"). Pass --skip-af1 to bypass
when bastion is unavailable (e.g. local unit tests).

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# --- Result types ---------------------------------------------------------


@dataclass
class AssertionResult:
    id: str
    result: str  # "PASS" | "FAIL" | "SKIP"
    severity: str  # "hard" | "soft"
    detail: str = ""
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "result": self.result, "severity": self.severity}
        if self.detail:
            d["detail"] = self.detail
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        return d


@dataclass
class Verdict:
    overall: str = "PASS"
    assertions: list[AssertionResult] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "assertions": [a.to_dict() for a in self.assertions],
            "summary": self.summary,
        }


# --- Manifest helpers -----------------------------------------------------


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_states(tests: list[dict]) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 0,
              "running": 0, "retriable_error": 0, "fixed_pending_verify": 0}
    for t in tests:
        s = t.get("status", "pending")
        counts[s] = counts.get(s, 0) + 1
    return counts


# --- Assertion evaluators -------------------------------------------------


def eval_terminal_state(expected: dict, manifest: dict) -> list[AssertionResult]:
    tests = manifest.get("tests", [])
    counts = _count_states(tests)

    # Two shapes in fixtures: {"required": {...}} (L1/L2/L3) or
    # {"expected_offline": {...}} (L4). Prefer "required" then fall back.
    target = expected.get("required") or expected.get("expected_offline") or {}
    results: list[AssertionResult] = []

    if not target:
        results.append(AssertionResult(
            id="TSD", result="SKIP", severity="soft",
            detail="terminal_state_distribution present but no required/expected_offline key",
        ))
        return results

    mismatches = []
    for k, want in target.items():
        if k.startswith("_"):
            continue
        got = counts.get(k, 0)
        if got != want:
            mismatches.append(f"{k}={got}!={want}")
    actual_subset = {k: counts.get(k, 0) for k in target if not k.startswith("_")}

    if mismatches:
        results.append(AssertionResult(
            id="TSD", result="FAIL", severity="hard",
            detail="; ".join(mismatches), expected=target, actual=actual_subset,
        ))
    else:
        results.append(AssertionResult(
            id="TSD", result="PASS", severity="hard",
            expected=target, actual=actual_subset,
        ))
    return results


def eval_anti_fabrication(
    assertions: list[dict],
    manifest: dict,
    bastion_profile: str,
    skip_af1: bool,
    agent_cmd: list[str],
) -> list[AssertionResult]:
    tests = manifest.get("tests", [])
    results: list[AssertionResult] = []
    expected_total = manifest.get("statistics", {}).get("total") or len(tests)

    for a in assertions:
        aid = a["id"]
        sev = a.get("severity", "hard")

        if aid == "AF-1":
            if skip_af1:
                results.append(AssertionResult(
                    id=aid, result="SKIP", severity=sev,
                    detail="--skip-af1 set; remote log stat bypassed",
                ))
                continue
            bad = []
            # An "executed" entry is one that actually ran on the remote — use
            # run_count > 0 as the truth (status alone is ambiguous: `ignored`
            # covers both ran-and-gave-up and never-ran). Every executed entry
            # MUST carry a non-empty log_file that stats successfully; absence
            # is itself the canonical fabrication signal.
            for t in tests:
                if t.get("run_count", 0) <= 0:
                    continue
                log = t.get("log_file")
                if not log:
                    bad.append(f"{t.get('test_node')}: run_count>0 but log_file is null/empty")
                    continue
                size = _remote_stat_size(agent_cmd, bastion_profile, log)
                if size is None or size <= 0:
                    bad.append(f"{t.get('test_node')}: log_file={log!r} size={size}")
            if bad:
                results.append(AssertionResult(
                    id=aid, result="FAIL", severity=sev,
                    detail=f"{len(bad)} log_file(s) missing or empty",
                    actual=bad[:5],
                ))
            else:
                results.append(AssertionResult(id=aid, result="PASS", severity=sev))

        elif aid == "AF-2":
            violations = []
            for t in tests:
                status = t.get("status")
                dur = t.get("last_duration_ms")
                run_count = t.get("run_count", 0)
                if status in ("passed", "failed"):
                    if not (isinstance(dur, int) and dur > 0):
                        violations.append(f"{t.get('test_node')}: status={status} but last_duration_ms={dur!r}")
                elif status == "ignored" and run_count == 0:
                    if dur is not None:
                        violations.append(f"{t.get('test_node')}: status=ignored run_count=0 but last_duration_ms={dur!r}")
            if violations:
                results.append(AssertionResult(
                    id=aid, result="FAIL", severity=sev,
                    detail=f"{len(violations)} duration anomalies",
                    actual=violations[:5],
                ))
            else:
                results.append(AssertionResult(id=aid, result="PASS", severity=sev))

        elif aid == "AF-3":
            counts = _count_states(tests)
            accounted = counts["passed"] + counts["failed"] + counts["ignored"]
            if accounted != expected_total:
                results.append(AssertionResult(
                    id=aid, result="FAIL", severity=sev,
                    detail=f"passed({counts['passed']})+failed({counts['failed']})+ignored({counts['ignored']})={accounted} != total({expected_total})",
                    actual={"accounted": accounted, "expected_total": expected_total},
                ))
            else:
                results.append(AssertionResult(
                    id=aid, result="PASS", severity=sev,
                    actual={"accounted": accounted, "expected_total": expected_total},
                ))
        else:
            results.append(AssertionResult(
                id=aid, result="SKIP", severity=sev,
                detail=f"unknown anti_fabrication id {aid!r}",
            ))
    return results


def _remote_stat_size(agent_cmd: list[str], profile: str, log_file: str) -> int | None:
    """Run `<agent_cmd> -p <profile> run "stat -c %s <log_file>"` and parse size.
    Returns None on failure."""
    cmd = agent_cmd + ["-p", profile, "run", f"stat -c %s {log_file}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def eval_stage_invariants(
    invariants: list[dict],
    manifest: dict,
    batch_results: list[dict],
    max_retry_per_test: int,
) -> list[AssertionResult]:
    tests = manifest.get("tests", [])
    results: list[AssertionResult] = []
    for inv in invariants:
        iid = inv["id"]
        sev = inv.get("severity", "hard")
        if iid == "STG-1":
            any_retry = any((t.get("retry_count", 0) > 0) for t in tests)
            any_retriable = False
            for br in batch_results:
                for entry in br.get("tests", []) or br.get("results", []) or []:
                    if entry.get("final_status") == "retriable_error" or entry.get("status") == "retriable_error":
                        any_retriable = True
                        break
            if any_retry or any_retriable:
                results.append(AssertionResult(id=iid, result="PASS", severity=sev))
            else:
                results.append(AssertionResult(
                    id=iid, result="FAIL", severity=sev,
                    detail="no test had retry_count>0 and no batch_results entry hit retriable_error",
                ))
        elif iid == "STG-2":
            bad = [t for t in tests if t.get("retry_count", 0) > max_retry_per_test]
            if bad:
                results.append(AssertionResult(
                    id=iid, result="FAIL", severity=sev,
                    detail=f"{len(bad)} test(s) over retry budget {max_retry_per_test}",
                    actual=[t.get("test_node") for t in bad[:5]],
                ))
            else:
                results.append(AssertionResult(id=iid, result="PASS", severity=sev))
        elif iid == "STG-3":
            stuck = [t for t in tests if t.get("status") == "retriable_error"]
            if stuck:
                results.append(AssertionResult(
                    id=iid, result="FAIL", severity=sev,
                    detail=f"{len(stuck)} test(s) terminal in retriable_error (must be promoted)",
                    actual=[t.get("test_node") for t in stuck[:5]],
                ))
            else:
                results.append(AssertionResult(id=iid, result="PASS", severity=sev))
        else:
            results.append(AssertionResult(
                id=iid, result="SKIP", severity=sev,
                detail=f"unknown stage_invariant id {iid!r}",
            ))
    return results


def eval_dependency_chain(
    invariants: list[dict],
    batch_results: list[dict],
    manifest: dict | None = None,
) -> list[AssertionResult]:
    """Dependency-chain invariants.

    INV-1..5 require Kanban gateway timestamps + round-by-round batch results.
    Without an external `kanban_audit.json`, they remain SKIP — the Kanban
    inspector script (TBD) is responsible for the heavy lifting; we stub here
    so the JSON shape is stable.

    INV-6 (added 2026-06-23 per L4 postmortem §4): terminal `pending == 0`.
    This is a hard contract that the fixer → dependency-resolver loop closes
    every `pending` task (resolver promotes to `ignored` on failure). It can
    be evaluated locally from the manifest, with no Kanban audit needed.
    """
    results = []
    for inv in invariants:
        iid = inv.get("id", "")
        if iid == "INV-6":
            if manifest is None:
                results.append(AssertionResult(
                    id=iid, result="SKIP", severity=inv.get("severity", "hard"),
                    detail="INV-6 requires manifest (not provided)",
                ))
                continue
            counts = _count_states(manifest.get("tests", []))
            pending = counts.get("pending", 0)
            if pending == 0:
                results.append(AssertionResult(
                    id=iid, result="PASS", severity=inv.get("severity", "hard"),
                    detail="terminal pending == 0 (resolver loop closed)",
                ))
            else:
                results.append(AssertionResult(
                    id=iid, result="FAIL", severity=inv.get("severity", "hard"),
                    detail=f"{pending} pending test(s) at terminal — "
                           f"resolver may be missing or stuck "
                           f"(check ut-dependency-resolver gateway)",
                ))
        else:
            results.append(AssertionResult(
                id=iid, result="SKIP", severity=inv.get("severity", "hard"),
                detail="dependency-chain check requires kanban_audit; not yet wired into check_expected.py",
            ))
    return results


# --- Driver ---------------------------------------------------------------


def evaluate(
    run_dir: Path,
    expected: dict,
    skip_af1: bool,
    agent_cmd: list[str],
) -> Verdict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return Verdict(
            overall="FAIL",
            assertions=[AssertionResult(
                id="META", result="FAIL", severity="hard",
                detail=f"manifest.json not found at {manifest_path}",
            )],
            summary="manifest.json missing",
        )
    manifest = _load_json(manifest_path)

    batch_results: list[dict] = []
    for br in sorted(run_dir.glob("batches/*/batch_results.json")):
        try:
            batch_results.append(_load_json(br))
        except Exception:
            pass

    metadata = expected.get("metadata", {})
    bastion_profile = metadata.get("bastion_profile", "t_h20")
    max_retry = metadata.get("max_retry_per_test", 3)

    verdict = Verdict()

    if "terminal_state_distribution" in expected:
        verdict.assertions.extend(eval_terminal_state(
            expected["terminal_state_distribution"], manifest,
        ))
    if "anti_fabrication_assertions" in expected:
        verdict.assertions.extend(eval_anti_fabrication(
            expected["anti_fabrication_assertions"], manifest,
            bastion_profile, skip_af1, agent_cmd,
        ))
    if "stage_invariants" in expected:
        verdict.assertions.extend(eval_stage_invariants(
            expected["stage_invariants"], manifest, batch_results, max_retry,
        ))
    if "dependency_chain_invariants" in expected:
        verdict.assertions.extend(eval_dependency_chain(
            expected["dependency_chain_invariants"], batch_results, manifest,
        ))
    if "per_test" in expected:
        verdict.assertions.append(AssertionResult(
            id="PER_TEST", result="SKIP", severity="soft",
            detail=f"{len(expected['per_test'])} per_test trajectory entries (informational only)",
        ))

    hard_total = sum(1 for a in verdict.assertions if a.severity == "hard")
    hard_pass = sum(1 for a in verdict.assertions if a.severity == "hard" and a.result == "PASS")
    hard_fail = sum(1 for a in verdict.assertions if a.severity == "hard" and a.result == "FAIL")

    verdict.overall = "PASS" if hard_fail == 0 else "FAIL"
    verdict.summary = (
        f"{hard_pass}/{hard_total} hard assertions pass"
        + (f"; {hard_fail} fail" if hard_fail else "")
    )
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Run-vs-expected comparator for UT tier fixtures")
    parser.add_argument("--run-dir", required=True, type=Path,
                        help="run directory containing manifest.json and batches/")
    parser.add_argument("--expected", required=True, type=Path,
                        help="expected-outcome JSON fixture (e.g. L4_expected.json)")
    parser.add_argument("--output-card-json", type=Path, default=None,
                        help="write verdict JSON to this file instead of stdout")
    parser.add_argument("--skip-af1", action="store_true",
                        help="skip AF-1 remote log stat (use when bastion not available)")
    parser.add_argument("--agent-cmd", default="tools/agent.py",
                        help="path to agent.py (default: tools/agent.py)")
    args = parser.parse_args()

    if not args.run_dir.exists():
        print(f"ERROR: run-dir does not exist: {args.run_dir}", file=sys.stderr)
        return 2
    try:
        expected = _load_json(args.expected)
    except Exception as e:
        print(f"ERROR: cannot parse expected file {args.expected}: {e}", file=sys.stderr)
        return 2

    agent_cmd = [sys.executable, args.agent_cmd] if args.agent_cmd.endswith(".py") else [args.agent_cmd]

    verdict = evaluate(args.run_dir, expected, args.skip_af1, agent_cmd)
    payload = json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False)

    if args.output_card_json:
        args.output_card_json.write_text(payload, encoding="utf-8")
    else:
        print(payload)

    return 0 if verdict.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
