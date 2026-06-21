#!/usr/bin/env python3
"""deploy_l4_profiles.py - install/verify the 4 frozen Hermes profiles for L4.

The L4 Kanban test needs 4 Hermes agent profiles (ut-orchestrator / ut-executor
/ ut-fixer / ut-supervisor). Their *behavior-defining* files are frozen in this
repo under tests/ut/integration/fixtures/profiles/<name>/:

    profile.yaml            # description (minimal Hermes schema)
    channel_directory.json  # Feishu chat binding (platforms.feishu[].id)
    SOUL.md                 # the agent persona / instructions (the real freeze)

This script copies ONLY those 3 files into the live Hermes profile dir
(~/AppData/Local/hermes/profiles/<name>/). It deliberately does NOT touch:
    auth.json / *.lock      # secrets / locks
    config.yaml             # machine-specific provider config + ${ENV} api keys
    state.db* / sessions /  # runtime state
    caches / logs / gateway*

Usage:
    python tests/ut/integration/deploy_l4_profiles.py --check   # diff only, no write
    python tests/ut/integration/deploy_l4_profiles.py           # install (prompts none)
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

# tests/ut/integration/deploy_l4_profiles.py -> project root is three levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FIXTURE_PROFILES = _PROJECT_ROOT / "tests" / "ut" / "integration" / "fixtures" / "profiles"
_HERMES_PROFILES = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

_PROFILES = ["ut-orchestrator", "ut-executor", "ut-fixer", "ut-supervisor"]
_FILES = ["profile.yaml", "channel_directory.json", "SOUL.md"]


def _status(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "NEW"
    if filecmp.cmp(src, dst, shallow=False):
        return "SAME"
    return "DIFF"


def run(check_only: bool) -> bool:
    if not _FIXTURE_PROFILES.exists():
        print(f"[X] frozen profiles not found: {_FIXTURE_PROFILES}")
        return False

    ok = True
    for profile in _PROFILES:
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
    print("Verify: python tests/ut/integration/start_l4_test.py --status")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Install/verify frozen L4 Hermes profiles")
    parser.add_argument("--check", action="store_true", help="Diff only, do not write")
    args = parser.parse_args()
    sys.exit(0 if run(args.check) else 1)


if __name__ == "__main__":
    main()
