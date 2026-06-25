#!/usr/bin/env python3
"""deploy_tier.py — install/verify Hermes profiles as distributions per tier.

Each profile is shipped as a Hermes **profile distribution** (see
`hermes profile install` / `hermes profile update`). The distribution source is
assembled on the fly under `.dist/<profile>/` from repo-owned authoritative
sources, then installed with `hermes profile install --force` (user data —
auth, sessions, state.db, .env — is preserved; only distribution-owned files
are overwritten).

Distribution-owned files (overwritten on every deploy):
    SOUL.md          <- tests/ut/integration/fixtures/profiles/<name>/SOUL.md
    profile.yaml     <- tests/ut/integration/fixtures/profiles/<name>/profile.yaml
    skills/ut/<subset> <- repo root skills/ut/<skill>/ (the authoritative source)

User-owned (NEVER touched — kept by hermes profile install --force):
    channel_directory.json  # Feishu chat binding, machine-specific
    auth.json, .env, config.yaml, state.db*, sessions/, logs/, gateway*, ...

Tier -> profile set:
    L1 / L2 / L3 (linear, kanban OFF):   [ut-supervisor]
    L4           (kanban ON):            [ut-orchestrator, ut-executor, ut-fixer, ut-supervisor]

Profile -> skills subset (per hermes_workflow SKILL §3 step 3 + §6 worker
Stage mapping; the repo root skills/ut/ pool also holds ut-test-collector and
workflow which belong to the linear channel / Stage 1 and are NOT hermes
profile skills):
    ut-supervisor    : hermes_workflow, workflow_loop_core, batch-selector,
                       unit-test-executor, failure-handler, manifest-updater,
                       shared
    ut-orchestrator  : batch-selector, manifest-updater, shared  # Stage5+Stage2
    ut-executor      : unit-test-executor, shared                # Stage3
    ut-fixer         : failure-handler, dependency-resolver, shared  # Stage4

Note: `shared/` carries cross-skill schemas + validators (manifest_schema.json,
batch_results_schema.json, handled_tests_schema.json, dependency_stall_schema.json,
validate_schema.py). Every profile that runs Python from skills/ut/* imports
from `skills.ut.shared`, so it must ship with the profile.

Usage:
    python tasks/ut/scripts/deploy_tier.py --tier L1 --check
    python tasks/ut/scripts/deploy_tier.py --tier L4
    python tasks/ut/scripts/deploy_tier.py --tier L4 --profile ut-supervisor

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §5 P1d
"""

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

# tasks/ut/scripts/deploy_tier.py -> project root is four levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FIXTURE_PROFILES = _PROJECT_ROOT / "tests" / "ut" / "integration" / "fixtures" / "profiles"
_REPO_SKILLS = _PROJECT_ROOT / "skills" / "ut"
_DIST_ROOT = Path(__file__).resolve().parent / ".dist"
_HERMES_PROFILES = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

# distribution_owned: files hermes profile install/update will overwrite.
# channel_directory.json is deliberately user-owned (machine-specific Feishu binding).
_DIST_OWNED_FILES = ["SOUL.md", "profile.yaml"]

_LINEAR_PROFILES = ["ut-supervisor"]
_KANBAN_PROFILES = ["ut-orchestrator", "ut-executor", "ut-fixer", "ut-supervisor"]

_TIER_PROFILES: dict[str, list[str]] = {
    "L1": _LINEAR_PROFILES,
    "L2": _LINEAR_PROFILES,
    "L3": _LINEAR_PROFILES,
    "L4": _KANBAN_PROFILES,
}

# Profile -> skills subset (names of subdirs under repo root skills/ut/).
# Derived from hermes_workflow SKILL §3 step 3 (supervisor load list) and
# §6 (worker Stage ownership). See module docstring.
_PROFILE_SKILLS: dict[str, list[str]] = {
    "ut-supervisor": [
        "hermes_workflow",
        "workflow_loop_core",
        "batch-selector",
        "unit-test-executor",
        "failure-handler",
        "manifest-updater",
        "shared",
    ],
    "ut-orchestrator": ["batch-selector", "manifest-updater", "shared"],
    "ut-executor": ["unit-test-executor", "shared"],
    "ut-fixer": ["failure-handler", "dependency-resolver", "shared"],
    "ut-batch-selector": ["batch-selector", "workflow_loop_core", "shared"],  # Stage2 Worker Kanban
    "ut-manifest-updater": ["manifest-updater", "workflow_loop_core", "shared"],  # Stage5 Worker Kanban
}

DISTRIBUTION_YAML = """\
name: {name}
version: 0.1.0
description: "UT Workflow profile '{name}' — distributed from apmm repo skills/ut + fixtures/profiles/{name}."
hermes_requires: ">=0.12.0"
author: liux
distribution_owned:
  - SOUL.md
  - profile.yaml
  - skills/
"""


def _status(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "NEW"
    if filecmp.cmp(src, dst, shallow=False):
        return "SAME"
    return "DIFF"


def _assemble_distribution(profile: str) -> Path:
    """Assemble `.dist/<profile>/` from repo sources. Returns the dist dir.

    Layout:
        .dist/<profile>/distribution.yaml
        .dist/<profile>/SOUL.md
        .dist/<profile>/profile.yaml
        .dist/<profile>/skills/ut/<skill>/...   (subset per _PROFILE_SKILLS)
    """
    src_dir = _FIXTURE_PROFILES / profile
    dist_dir = _DIST_ROOT / profile
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    # distribution.yaml
    (dist_dir / "distribution.yaml").write_text(
        DISTRIBUTION_YAML.format(name=profile), encoding="utf-8"
    )

    # SOUL.md + profile.yaml from fixtures
    for fname in _DIST_OWNED_FILES:
        src = src_dir / fname
        if not src.exists():
            raise FileNotFoundError(f"missing fixture file: {src}")
        shutil.copy2(src, dist_dir / fname)

    # skills/ut/<subset> from repo root authoritative source
    skills_dst = dist_dir / "skills" / "ut"
    skills_dst.mkdir(parents=True)
    for skill in _PROFILE_SKILLS[profile]:
        skill_src = _REPO_SKILLS / skill
        if not skill_src.is_dir():
            raise FileNotFoundError(f"missing repo skill: {skill_src}")
        shutil.copytree(skill_src, skills_dst / skill)

    return dist_dir


def _install_distribution(profile: str, dist_dir: Path) -> bool:
    """Run `hermes profile install <dist_dir> --name <profile> --force -y`."""
    cmd = [
        "hermes", "profile", "install", str(dist_dir),
        "--name", profile, "--force", "-y",
    ]
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    # Print hermes output safely — stdout may be GBK on Windows and contain
    # emoji (e.g. ⚠) that can't encode. Decode to ASCII-safe form for display.
    for stream in (r.stdout, r.stderr):
        if stream.strip():
            safe = stream.encode("ascii", errors="replace").decode("ascii")
            print("  " + safe.strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print(f"  [X] hermes profile install failed (rc={r.returncode})")
        return False
    return True


def _check_profile(profile: str) -> bool:
    """Diff repo sources vs live Hermes profile (no write)."""
    src_dir = _FIXTURE_PROFILES / profile
    dst_dir = _HERMES_PROFILES / profile
    print(f"\n=== {profile} ===")
    if not src_dir.exists():
        print(f"  [X] missing fixture dir: {src_dir}")
        return False
    if not dst_dir.exists():
        print(f"  [!] live profile dir absent ({dst_dir}).")
        print(f"      create the profile in Hermes first: hermes profile create {profile}")
        return False

    ok = True
    # distribution status: dist profiles print "Distribution: <name>" as the
    # first non-blank line; non-dist prints "is not a distribution".
    info = subprocess.run(["hermes", "profile", "info", profile],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    combined = info.stdout + info.stderr
    is_dist = combined.lstrip().startswith("Distribution:")
    print(f"  [{'DIST' if is_dist else 'NON-DIST'}] hermes profile info")

    # SOUL.md + profile.yaml
    for fname in _DIST_OWNED_FILES:
        src = src_dir / fname
        dst = dst_dir / fname
        if not src.exists():
            print(f"  [X] missing fixture file: {src}")
            ok = False
            continue
        print(f"  [{_status(src, dst):<4}] {fname}")

    # skills/ut/<subset>
    for skill in _PROFILE_SKILLS[profile]:
        src = _REPO_SKILLS / skill
        dst = dst_dir / "skills" / "ut" / skill
        if not src.is_dir():
            print(f"  [X] missing repo skill: {src}")
            ok = False
            continue
        skill_status = _dir_status(src, dst)
        print(f"  [{skill_status:<4}] skills/ut/{skill}")
        if skill_status == "X":
            ok = False
    return ok


def _dir_status(src: Path, dst: Path) -> str:
    """SAME if every file under src exists in dst and matches; else DIFF/NEW."""
    if not dst.exists():
        return "NEW"
    for src_file in src.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src)
        dst_file = dst / rel
        if not dst_file.exists() or not filecmp.cmp(src_file, dst_file, shallow=False):
            return "DIFF"
    return "SAME"


def run(tier: str, check_only: bool, only_profile: str | None) -> bool:
    tier = tier.upper()
    if tier not in _TIER_PROFILES:
        print(f"[X] unknown tier: {tier!r} (known: {sorted(_TIER_PROFILES)})")
        return False
    profiles = _TIER_PROFILES[tier]
    if only_profile:
        if only_profile not in profiles:
            print(f"[X] --profile {only_profile!r} not in tier {tier} set {profiles}")
            return False
        profiles = [only_profile]
    print(f"Tier {tier}: {'checking' if check_only else 'deploying'} "
          f"{len(profiles)} profile(s): {profiles}")

    if not _FIXTURE_PROFILES.exists():
        print(f"[X] fixture profiles dir not found: {_FIXTURE_PROFILES}")
        return False
    if not _REPO_SKILLS.is_dir():
        print(f"[X] repo skills dir not found: {_REPO_SKILLS}")
        return False

    ok = True
    for profile in profiles:
        if check_only:
            ok = _check_profile(profile) and ok
        else:
            print(f"\n=== {profile} ===")
            try:
                dist_dir = _assemble_distribution(profile)
            except FileNotFoundError as e:
                print(f"  [X] {e}")
                ok = False
                continue
            if not (_HERMES_PROFILES / profile).exists():
                print(f"  [!] live profile dir absent. "
                      f"Create first: hermes profile create {profile}")
                ok = False
                continue
            ok = _install_distribution(profile, dist_dir) and ok

    print("\n" + ("Check complete (no files written)." if check_only
                  else "Deploy complete."))
    print("Verify: python tasks/ut/scripts/start_hermes_ut_runtime.py --status")
    print("        hermes profile info <profile>   # confirm 'is a distribution'")
    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Install/verify Hermes profile distributions per tier")
    parser.add_argument("--tier", required=True, choices=sorted(_TIER_PROFILES),
                        help="Tier to deploy (L1/L2/L3=supervisor only; L4=all four)")
    parser.add_argument("--check", action="store_true", help="Diff only, do not write")
    parser.add_argument("--profile", help="Restrict to one profile within the tier set")
    args = parser.parse_args()
    sys.exit(0 if run(args.tier, args.check, args.profile) else 1)


if __name__ == "__main__":
    main()
