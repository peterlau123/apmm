#!/usr/bin/env python3
"""refresh_profile.py — ensure ut-supervisor profile SOUL.md matches repo source.

Called at the start of the startup sequence (Step 0) so the supervisor always
runs with the latest profile instructions. Copies SOUL.md and profile.yaml
from the repo fixture to the live Hermes profile directory.

Safe to call multiple times — only overwrites distribution-owned files.
"""
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
FIXTURE_DIR = PROJECT_ROOT / "tests" / "ut" / "integration" / "fixtures" / "profiles"
PROFILE_DIR = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

DIST_FILES = ["SOUL.md", "profile.yaml"]


def refresh(profile: str = "ut-supervisor") -> bool:
    """Copy distribution-owned files from repo fixture to live profile.

    Args:
        profile: Profile name (default: ut-supervisor).

    Returns:
        True if refresh was needed and completed, False if already current.
    """
    fixture = FIXTURE_DIR / profile
    live = PROFILE_DIR / profile

    if not fixture.exists():
        print(f"[refresh] fixture not found: {fixture}", file=sys.stderr)
        return False

    if not live.exists():
        print(f"[refresh] live profile not found: {live}", file=sys.stderr)
        print(f"  Create first: hermes profile create {profile}", file=sys.stderr)
        return False

    refreshed = False
    for filename in DIST_FILES:
        src = fixture / filename
        dst = live / filename

        if not src.exists():
            print(f"[refresh] source not found: {src}", file=sys.stderr)
            continue

        if dst.exists() and src.read_bytes() == dst.read_bytes():
            continue  # already current

        shutil.copy2(src, dst)
        print(f"[refresh] updated {filename}: {src.name} -> {dst}")
        refreshed = True

    if not refreshed:
        print(f"[refresh] profile {profile} is already current")
    return refreshed


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Refresh ut-supervisor profile from repo fixtures"
    )
    parser.add_argument(
        "--profile", default="ut-supervisor",
        help="Profile name (default: ut-supervisor)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check only, do not copy",
    )
    args = parser.parse_args()

    if args.check:
        fixture = FIXTURE_DIR / args.profile
        live = PROFILE_DIR / args.profile
        outdated = []
        for filename in DIST_FILES:
            src = fixture / filename
            dst = live / filename
            if src.exists() and dst.exists() and src.read_bytes() != dst.read_bytes():
                outdated.append(filename)
        if outdated:
            print(f"Outdated files: {outdated}")
        else:
            print(f"Profile {args.profile} is current")
        return

    ok = refresh(args.profile)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
