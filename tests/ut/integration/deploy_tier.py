#!/usr/bin/env python3
"""deploy_tier.py — install/verify the frozen Hermes profiles for a tier.

Tier -> profile set:
    L1 / L2 / L3 (linear, kanban OFF):   [ut-supervisor]
    L4           (kanban ON):            [ut-orchestrator, ut-executor, ut-fixer, ut-supervisor]

Each profile's *behavior-defining* files are frozen in this repo under
    tests/ut/integration/fixtures/profiles/<name>/

        profile.yaml            # description (minimal Hermes schema)
        channel_directory.json  # Feishu chat binding (platforms.feishu[].id)
        SOUL.md                 # the agent persona / instructions (the real freeze)

This script copies ONLY those 3 files into the live Hermes profile dir
(~/AppData/Local/hermes/profiles/<name>/). It deliberately does NOT touch
auth.json, *.lock, config.yaml, state.db, sessions/, caches/, logs/, gateway*.

Usage:
    python tests/ut/integration/deploy_tier.py --tier L1 --check
    python tests/ut/integration/deploy_tier.py --tier L4

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §5 P1d
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

# tests/ut/integration/deploy_tier.py -> project root is three levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FIXTURE_PROFILES = _PROJECT_ROOT / "tests" / "ut" / "integration" / "fixtures" / "profiles"
_HERMES_PROFILES = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

_LINEAR_PROFILES = ["ut-supervisor"]
_KANBAN_PROFILES = ["ut-orchestrator", "ut-executor", "ut-fixer", "ut-supervisor"]

_TIER_PROFILES: dict[str, list[str]] = {
    "L1": _LINEAR_PROFILES,
    "L2": _LINEAR_PROFILES,
    "L3": _LINEAR_PROFILES,
    "L4": _KANBAN_PROFILES,
}

_FILES = ["profile.yaml", "channel_directory.json", "SOUL.md"]


def _status(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "NEW"
    if filecmp.cmp(src, dst, shallow=False):
        return "SAME"
    return "DIFF"


def run(tier: str, check_only: bool) -> bool:
    tier = tier.upper()
    if tier not in _TIER_PROFILES:
        print(f"[X] unknown tier: {tier!r} (known: {sorted(_TIER_PROFILES)})")
        return False
    profiles = _TIER_PROFILES[tier]
    print(f"Tier {tier}: deploying {len(profiles)} profile(s): {profiles}")

    if not _FIXTURE_PROFILES.exists():
        print(f"[X] frozen profiles dir not found: {_FIXTURE_PROFILES}")
        return False

    ok = True
    for profile in profiles:
        src_dir = _FIXTURE_PROFILES / profile
        dst_dir = _HERMES_PROFILES / profile
        print(f"\n=== {profile} ===")
        if not src_dir.exists():
            print(f"  [X] missing frozen dir: {src_dir}")
            ok = False
            continue
        if not dst_dir.exists():
            print(f"  [!] live profile dir absent ({dst_dir}).")
            print(f"      create the profile in Hermes first: hermes profile create {profile}")
            ok = False
            continue

        for fname in _FILES:
            src = src_dir / fname
            dst = dst_dir / fname
            if not src.exists():
                print(f"  [X] frozen file missing: {src}")
                ok = False
                continue
            st = _status(src, dst)
            if check_only:
                print(f"  [{st:<4}] {fname}")
            else:
                if st == "SAME":
                    print(f"  [SAME] {fname} (skip)")
                else:
                    shutil.copy2(src, dst)
                    print(f"  [{'WROTE->' + st}] {fname}")

    print("\n" + ("Check complete (no files written)." if check_only else "Deploy complete."))
    print("Verify: python tasks/ut/scripts/start_hermes_ut_runtime.py --status")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Install/verify frozen Hermes profiles per tier")
    parser.add_argument("--tier", required=True, choices=sorted(_TIER_PROFILES),
                        help="Tier to deploy (L1/L2/L3=supervisor only; L4=all four)")
    parser.add_argument("--check", action="store_true", help="Diff only, do not write")
    args = parser.parse_args()
    sys.exit(0 if run(args.tier, args.check) else 1)


if __name__ == "__main__":
    main()
