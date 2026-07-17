# test_load 数据流修复 Implementation Plan

> **For Claude:** Use the Executing Plans skill to implement this plan task-by-task.

**Goal:** Fix all 7 issues from code review round 2 to make test_load data flow correctly end-to-end.

**Architecture:** test_load = working dataset (read/written during run), manifest = master record (updated only at end via update_manifest_from_test_load.py). v5 merge logic centralized in update_test_load.py, reused by update_test_load_two_phase.py.

**Tech Stack:** Python 3, argparse, jsonschema

---

### Task 1: Fix verify_manifest_updated to check test_load (P0 - P1)

**Files:**
- Modify: 	asks/ut/scripts/auto_run_batches_two_phase.py

**Step 1: Modify verify_manifest_updated function**

Replace the function to read test_load path from workflow_state and verify test_load (not manifest) was updated:

`python
def verify_batch_updated(batch_id: str, workflow_state_path: Path) -> bool:
    """Checkpoint 4: Verify test_load was updated for batch

    Reads test_load path from workflow_state.json, then checks if any test
    has this batch_id with updated status (non-pending).
    """
    state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
    paths = state.get("paths", {})
    test_load_path = paths.get("test_load", "")
    if not test_load_path or not Path(test_load_path).exists():
        return False
    test_load = json.loads(Path(test_load_path).read_text(encoding="utf-8"))
    for test in test_load.get("tests", []):
        if test.get("last_batch_id") == batch_id:
            if test.get("status", "pending") != "pending":
                return True
    return False
`

**Step 2: Update the call site**

Change from:
`python
assert verify_manifest_updated(batch_id, manifest_path)
`
To:
`python
assert verify_batch_updated(batch_id, workflow_state_path)
`

**Step 3: Update comments**

Change "Stage 4: Manifest" comments to "Stage 4.5: test_load update".

**Step 4: Verify syntax**

Run: python -c "import py_compile; py_compile.compile(r'tasks/ut/scripts/auto_run_batches_two_phase.py', doraise=True)"
Expected: no error

---

### Task 2: Fix SKILL.md code fence and description (S1, S2)

**Files:**
- Modify: skills/ut/terminal-workflow/SKILL.md
- Modify: skills/ut/hermes-workflow/SKILL.md

**Step 1: Fix closing code fence (byte-level)**

In both files, replace single backtick closing fence with triple backtick.
The pattern is: line containing only a single backtick character (0x60) after
the generate_test_load.py command block.

**Step 2: Fix Retry section description**

In both files, change:
`
- manifest.json - 测试清单（非manifest.json）
`
To:
`
- 	est_load_xxx.json - 测试清单（工作数据集，非manifest.json）
`

**Step 3: Verify no corruption remains**

Run: python -c "from pathlib import Path; c=Path(r'skills/ut/terminal-workflow/SKILL.md').read_text(encoding='utf-8'); assert '\x08' not in c; print('OK')"

---

### Task 3: Enhance update_manifest_from_test_load.py with v5 fields (P2)

**Files:**
- Modify: skills/ut/manifest-updater/scripts/update_manifest_from_test_load.py

**Step 1: Add v5 field copying**

In the update loop, after copying status, add:
`python
# Copy v5 merge fields
for field in ("retry_count", "ignore_reason", "error_type", "error_message",
              "last_batch_id", "commit", "errors", "failures",
              "duration_ms", "exit_code", "log_file", "run_at"):
    if field in test_load_test:
        manifest_tests[test_node][field] = test_load_test[field]
`

**Step 2: Replace defaultdict statistics with calculate_statistics import**

Add import and replace the statistics calculation:
`python
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from skills.ut.manifest_updater.scripts.update_status import calculate_statistics
`

Replace the defaultdict block with:
`python
manifest["statistics"] = calculate_statistics(manifest["tests"])
`

**Step 3: Verify syntax**

Run: python -c "import py_compile; py_compile.compile(r'skills/ut/manifest-updater/scripts/update_manifest_from_test_load.py', doraise=True)"

---

### Task 4: Add dependency direction comment (S5)

**Files:**
- Modify: skills/ut/ut_common/update_test_load_two_phase.py

**Step 1: Add explanatory comment**

Before the import line, add:
`python
# NOTE: This imports from manifest-updater (higher-level module) to reuse
# the v5 merge logic. This is an intentional upward dependency -- the
# alternative (duplicating merge_batch_results) would violate DRY.
`

**Step 2: Verify syntax**

Run: python -c "import py_compile; py_compile.compile(r'skills/ut/ut_common/update_test_load_two_phase.py', doraise=True)"

---

### Task 5: Final verification

**Step 1: Run comprehensive syntax checks**

`python
import py_compile
for f in [all modified .py files]:
    py_compile.compile(f, doraise=True)
`

**Step 2: Verify no Markdown corruption**

Check all SKILL.md files for backspace (0x08) characters.

**Step 3: Verify data flow consistency**

- generate_batch.py reads test_load first
- update_test_load_two_phase.py writes to test_load
- verify_batch_updated checks test_load
- update_manifest_from_test_load.py syncs to manifest with v5 fields
