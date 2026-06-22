#!/usr/bin/env python3
"""
grade_tier.py — One-shot tier verdict orchestrator.

Wraps `check_expected.py` so a single command can grade a finished run:

    python tasks/ut/scripts/grade_tier.py --tier L4 --run-dir runs/ut-20260622-1234

It selects the right `Lx_expected.json`, evaluates the run's manifest.json (+
batches), prints a PASS/FAIL JSON verdict, optionally writes the verdict to a
file, and optionally pushes a Feishu PASS/FAIL card.

Exit codes match check_expected.py: 0 PASS, 1 FAIL, 2 structural error.

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §5
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent.parent.parent  # tasks/ut/scripts -> repo root
_FIXTURES = _REPO / "tests" / "ut" / "integration" / "fixtures"
_CHECK_EXPECTED = _THIS.parent / "check_expected.py"


def _load_check_expected():
    spec = importlib.util.spec_from_file_location("check_expected", _CHECK_EXPECTED)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_expected"] = mod  # required: @dataclass looks it up here
    spec.loader.exec_module(mod)
    return mod


def _resolve_expected(tier: str, override: Path | None) -> Path:
    if override is not None:
        return override
    p = _FIXTURES / f"{tier}_expected.json"
    if not p.exists():
        raise FileNotFoundError(f"expected fixture not found: {p}")
    return p


def _send_feishu_card(verdict_dict: dict, tier: str, run_dir: Path, feishu_config: Path) -> bool:
    """Best-effort: returns True on send success, False on any failure."""
    feishu_api_path = _REPO / "skills" / "ut" / "workflow" / "scripts" / "feishu_api.py"
    if not feishu_api_path.exists():
        print(f"[grade_tier] feishu_api.py not found at {feishu_api_path}; skipping card", file=sys.stderr)
        return False
    spec = importlib.util.spec_from_file_location("feishu_api", feishu_api_path)
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    try:
        api = fa.FeishuAPI(str(feishu_config))
        return bool(api.send_tier_completion_card(verdict_dict, tier, str(run_dir)))
    except Exception as e:
        print(f"[grade_tier] feishu card send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade a finished UT run against its tier baseline")
    parser.add_argument("--tier", required=True, choices=["L1", "L2", "L3", "L4"],
                        help="tier to grade against")
    parser.add_argument("--run-dir", required=True, type=Path,
                        help="finished run directory (must contain manifest.json)")
    parser.add_argument("--expected", type=Path, default=None,
                        help="override expected fixture (default: tests/ut/integration/fixtures/<tier>_expected.json)")
    parser.add_argument("--output-card-json", type=Path, default=None,
                        help="write verdict JSON to this file (default: <run-dir>/<tier>_verdict.json)")
    parser.add_argument("--skip-af1", action="store_true",
                        help="skip AF-1 remote log stat (bastion-free mode)")
    parser.add_argument("--agent-cmd", default="tools/agent.py",
                        help="path to agent.py for AF-1 remote stat (default: tools/agent.py)")
    parser.add_argument("--feishu", action="store_true",
                        help="push verdict as Feishu PASS/FAIL card")
    parser.add_argument("--feishu-config", type=Path, default=Path(".agents/feishu_config.json"),
                        help="path to feishu_config.json (default: .agents/feishu_config.json)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress stdout JSON dump (still writes --output-card-json)")
    args = parser.parse_args()

    if not args.run_dir.exists():
        print(f"ERROR: run-dir does not exist: {args.run_dir}", file=sys.stderr)
        return 2

    try:
        expected_path = _resolve_expected(args.tier, args.expected)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: cannot parse {expected_path}: {e}", file=sys.stderr)
        return 2

    check_expected = _load_check_expected()
    agent_cmd = (
        [sys.executable, args.agent_cmd]
        if args.agent_cmd.endswith(".py")
        else [args.agent_cmd]
    )

    verdict = check_expected.evaluate(args.run_dir, expected, args.skip_af1, agent_cmd)
    verdict_dict = verdict.to_dict()

    # Default output card path lives next to the run for traceability.
    out_path = args.output_card_json or (args.run_dir / f"{args.tier}_verdict.json")
    out_path.write_text(
        json.dumps(verdict_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not args.quiet:
        print(json.dumps(verdict_dict, indent=2, ensure_ascii=False))
        print(f"\n[grade_tier] {args.tier} verdict written to {out_path}", file=sys.stderr)
        print(f"[grade_tier] overall={verdict.overall} — {verdict.summary}", file=sys.stderr)

    if args.feishu:
        ok = _send_feishu_card(verdict_dict, args.tier, args.run_dir, args.feishu_config)
        print(f"[grade_tier] feishu card sent={ok}", file=sys.stderr)

    return 0 if verdict.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
