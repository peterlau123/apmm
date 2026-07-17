#!/usr/bin/env python3
"""rename_shared_to_ut_common.py - Atomically rename shared/ to ut_common/ and reorganize."""
import os, shutil, subprocess, glob

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def protect(path):
    run(f'git update-index --skip-worktree "{path}"')

# Step 1: Create ut_common/ directory structure
for d in ["skills/ut/ut_common", "skills/ut/ut_common/scripts",
          "skills/ut/ut_common/schemas", "skills/ut/ut_common/assets",
          "skills/ut/ut_common/tests"]:
    os.makedirs(d, exist_ok=True)
print("Step 1: Directory structure created")

# Step 2: Move files from shared/ to ut_common/
moves = {
    # Root modules (importable Python packages)
    "__init__.py": "__init__.py",
    "bastion_signals.py": "bastion_signals.py",
    "config_loader.py": "config_loader.py",
    "load_filter_rules.py": "load_filter_rules.py",
    "path_setup.py": "path_setup.py",
    "ut_runner.py": "ut_runner.py",
    "validate_schema.py": "validate_schema.py",
    "workflow_state_manager.py": "workflow_state_manager.py",
    "update_test_load_two_phase.py": "update_test_load_two_phase.py",
    "filter_rules.yaml": "filter_rules.yaml",
    # Scripts -> scripts/
    "scripts/check_environment.py": "scripts/check_environment.py",
    "migrate_manifest.py": "scripts/migrate_manifest.py",
    # Schemas -> schemas/
    "manifest_schema.json": "schemas/manifest_schema.json",
    "dependency_stall_schema.json": "schemas/dependency_stall_schema.json",
    # Assets -> assets/
    "manifest_example.json": "assets/manifest_example.json",
    # Tests -> tests/
    "tests/test_workflow_state_manager.py": "tests/test_workflow_state_manager.py",
}

for src_name, dst_name in moves.items():
    src = f"skills/ut/ut_common/{src_name}"
    dst = f"skills/ut/ut_common/{dst_name}"
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        run(f'git mv "{src}" "{dst}" 2>/dev/null || cp "{src}" "{dst}"')
        run(f'git add "{dst}"')
        protect(dst)

# Move two-phase-handler as-is
src = "skills/ut/ut_common/two-phase-handler"
dst = "skills/ut/ut_common/two-phase-handler"
if os.path.exists(src):
    run(f'git mv "{src}" "{dst}" 2>/dev/null || cp -r "{src}" "{dst}"')
    run(f'git add "{dst}"')
    for root, dirs, files in os.walk(dst):
        for f in files:
            if f.endswith(('.py', '.md')):
                p = os.path.join(root, f).replace(os.sep, '/')
                protect(p)

print("Step 2: Files moved from shared/ to ut_common/")

# Step 3: Move reverted files from terminal-workflow/
reverted = [
    ("skills/ut/terminal-workflow/scripts/bastion_manager.py", "skills/ut/ut_common/scripts/bastion_manager.py"),
    ("skills/ut/terminal-workflow/scripts/feishu_api.py", "skills/ut/ut_common/scripts/feishu_api.py"),
    ("skills/ut/terminal-workflow/scripts/start_gateway.py", "skills/ut/ut_common/scripts/start_gateway.py"),
    ("skills/ut/terminal-workflow/workflow_schema.yaml", "skills/ut/ut_common/schemas/workflow_schema.yaml"),
    ("skills/ut/terminal-workflow/workflow_state_schema.json", "skills/ut/ut_common/schemas/workflow_state_schema.json"),
]
for src, dst in reverted:
    if os.path.exists(src):
        run(f'git mv "{src}" "{dst}" 2>/dev/null || cp "{src}" "{dst}"')
        run(f'git rm -f "{src}" 2>/dev/null')
        run(f'git add "{dst}"')
        protect(dst)
        print(f"  Moved: {os.path.basename(src)}")

print("Step 3: Reverted files moved from terminal-workflow/")

# Step 4: Update all references globally
exclude_dirs = {".git", "__pycache__", ".ruff_cache", "node_modules", ".pi/cache"}
updated = []
for pattern in ["**/*.py", "**/*.md", "**/*.yaml", "**/*.yml", "**/*.json", "**/*.txt"]:
    for filepath in glob.glob(pattern, recursive=True):
        if any(exc in filepath for exc in exclude_dirs):
            continue
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            continue
        original = content
        content = content.replace("skills.ut.ut_common", "skills.ut.ut_common")
        content = content.replace("skills/ut/ut_common", "skills/ut/ut_common")
        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            updated.append(filepath)
            run(f'git add "{filepath}"')
            protect(filepath)

print(f"Step 4: Updated {len(updated)} files with new paths")

# Step 5: Update validate_schema.py schema paths to schemas/ subdir
vs = "skills/ut/ut_common/validate_schema.py"
if os.path.exists(vs):
    with open(vs, 'r', encoding='utf-8') as f:
        c = f.read()
    for s in ["manifest_schema.json", "workflow_state_schema.json",
              "workflow_schema.yaml", "dependency_stall_schema.json"]:
        c = c.replace(f'"skills/ut/ut_common/{s}"', f'"skills/ut/ut_common/schemas/{s}"')
    with open(vs, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Step 5: validate_schema.py schema paths updated")

# Step 6: Remove old shared/
run('rm -rf skills/ut/ut_common/__pycache__ skills/ut/ut_common/.ruff_cache')
for root, dirs, files in os.walk("skills/ut/ut_common", topdown=False):
    for f in files:
        p = os.path.join(root, f)
        run(f'git rm -f "{p}" 2>/dev/null || rm -f "{p}"')
    for d in dirs:
        try: os.rmdir(os.path.join(root, d))
        except: pass
try: os.rmdir("skills/ut/ut_common")
except: pass
print("Step 6: Old shared/ removed")

# Verification
print("\n=== VERIFICATION ===")
for root, dirs, files in os.walk("skills/ut/ut_common"):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.ruff_cache')]
    level = root.replace("skills/ut/ut_common", "").count(os.sep)
    indent = "  " * level
    print(f"{indent}{os.path.basename(root)}/")
    for f in sorted(files):
        print(f"{indent}  {f}")

print(f"\nshared/ exists: {os.path.exists('skills/ut/ut_common')}")
tw_bad = any(os.path.exists(f"skills/ut/terminal-workflow/{f}") for f in
             ["workflow_schema.yaml", "workflow_state_schema.json",
              "scripts/bastion_manager.py", "scripts/feishu_api.py", "scripts/start_gateway.py"])
print(f"terminal-workflow/ has reverted files: {tw_bad}")
