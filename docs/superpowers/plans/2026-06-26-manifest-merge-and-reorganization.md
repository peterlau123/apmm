# Manifest Merge & Directory Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge latest test_list with old manifest preserving passed status, reorganize dataset directory, delete legacy files, update PROGRESS.md

**Architecture:** Sequential execution: File reorganization → Delete legacy → Python script merge → Documentation update. Use git mv for history preservation, Python script for intelligent merge, verify at each stage.

**Tech Stack:** Python (json processing), Git (mv/rm), Markdown (PROGRESS.md)

---

## File Structure

**Create:**
- `tasks/ut/dataset/` (directory)
- `tasks/ut/scripts/migrate_manifest.py` (Python merge script)

**Move (git mv):**
- `tasks/ut/test_analysis/manifest.json` → `tasks/ut/dataset/manifest.json`
- `tasks/ut/test_analysis/test_list.txt` → `tasks/ut/dataset/test_list.txt`
- `tasks/ut/test_analysis/ut_test_list_full_20260624_173600.txt` → `tasks/ut/dataset/ut_test_list_full_20260624_173600.txt`

**Delete (git rm):**
- `tasks/ut/test_analysis/manifest_legacy.json`

**Modify:**
- `tasks/ut/dataset/manifest.json` (merge result)
- `tasks/ut/PROGRESS.md` (update stats + milestone)

**Preserve:**
- `tasks/ut/test_analysis/manifest.backup-2026-06-20.json`
- `tasks/ut/test_analysis/remote_log_summary/`

---

## Task 1: File Reorganization (子系统E)

**Files:**
- Create: `tasks/ut/dataset/` (directory)
- Move: `tasks/ut/test_analysis/manifest.json` → `tasks/ut/dataset/manifest.json`
- Move: `tasks/ut/test_analysis/test_list.txt` → `tasks/ut/dataset/test_list.txt`
- Move: `tasks/ut/test_analysis/ut_test_list_full_20260624_173600.txt` → `tasks/ut/dataset/ut_test_list_full_20260624_173600.txt`

- [ ] **Step 1: Create dataset directory**

```bash
mkdir -p tasks/ut/dataset
```

Verify: `ls -ld tasks/ut/dataset/` shows directory exists

- [ ] **Step 2: Move manifest.json preserving git history**

```bash
git mv tasks/ut/test_analysis/manifest.json tasks/ut/dataset/manifest.json
```

Verify: `git status` shows "renamed: tasks/ut/test_analysis/manifest.json -> tasks/ut/dataset/manifest.json"

- [ ] **Step 3: Move test_list.txt preserving git history**

```bash
git mv tasks/ut/test_analysis/test_list.txt tasks/ut/dataset/test_list.txt
```

Verify: `git status` shows "renamed: ...test_list.txt -> ...dataset/test_list.txt"

- [ ] **Step 4: Move latest test_list preserving git history**

```bash
git mv tasks/ut/test_analysis/ut_test_list_full_20260624_173600.txt tasks/ut/dataset/ut_test_list_full_20260624_173600.txt
```

Verify: `git status` shows "renamed: ...ut_test_list_full... -> ...dataset/ut_test_list_full..."

- [ ] **Step 5: Verify dataset directory contents**

```bash
ls -lh tasks/ut/dataset/
```

Expected output shows:
- `manifest.json` (15MB)
- `test_list.txt` (3.4MB)
- `ut_test_list_full_20260624_173600.txt` (3.5MB)

- [ ] **Step 6: Verify test_analysis remaining files**

```bash
ls -lh tasks/ut/test_analysis/
```

Expected output shows:
- `manifest.backup-2026-06-20.json` (13MB) - preserved
- `manifest_legacy.json` (16MB) - will delete in Task 2
- `remote_log_summary/` - preserved
- No manifest.json, test_list.txt, or ut_test_list_full files (moved)

- [ ] **Step 7: Commit file reorganization**

```bash
git commit -m "refactor(ut): reorganize test_analysis → dataset directory

- Move manifest.json to dataset/ (core input data)
- Move test_list.txt to dataset/ (old test list)
- Move ut_test_list_full_20260624_173600.txt to dataset/ (latest test list)
- Preserve manifest.backup and remote_log_summary in test_analysis/

Directory responsibilities:
- dataset/ → input data (manifest + test_list)
- test_analysis/ → output data (backup + analysis logs)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Delete Legacy File (子系统D)

**Files:**
- Delete: `tasks/ut/test_analysis/manifest_legacy.json`

- [ ] **Step 1: Verify legacy file exists before deletion**

```bash
ls -lh tasks/ut/test_analysis/manifest_legacy.json
```

Expected: File exists (16MB)

- [ ] **Step 2: Delete legacy file with git rm**

```bash
git rm tasks/ut/test_analysis/manifest_legacy.json
```

Verify: `git status` shows "deleted: tasks/ut/test_analysis/manifest_legacy.json"

- [ ] **Step 3: Verify file no longer exists**

```bash
ls tasks/ut/test_analysis/manifest_legacy.json 2>&1
```

Expected: Error message "No such file or directory"

- [ ] **Step 4: Commit legacy file deletion**

```bash
git commit -m "refactor(ut): delete manifest_legacy.json

- Remove outdated legacy manifest (16MB)
- Current manifest in dataset/ is authoritative
- Backup preserved in test_analysis/manifest.backup-2026-06-20.json

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Manifest Merge Script (子系统C)

**Files:**
- Create: `tasks/ut/scripts/migrate_manifest.py`
- Input: `tasks/ut/dataset/ut_test_list_full_20260624_173600.txt`
- Input: `tasks/ut/dataset/manifest.json`
- Input: `skills/ut/shared/manifest_schema.json`
- Output: `tasks/ut/dataset/manifest.json` (merged)

- [ ] **Step 1: Write migrate_manifest.py script**

Create file `tasks/ut/scripts/migrate_manifest.py` with complete Python code (parse_test_list, generate_empty_entry, merge_manifests, main functions).

**Script structure**:
- `parse_test_list()` → Read test_list txt, extract test_nodes (format: `tests/path/test_file.py::test_name`)
- `generate_empty_entry()` → Create default test entry (status=pending)
- `merge_manifests()` → 增量合并逻辑:
  1. Parse new test_list (33286 nodes)
  2. Extract old manifest passed tests (6411 passed_map)
  3. Generate skeleton entries
  4. Merge passed status + preserve fields: `log_file`, `last_run_at`, `error_type` (修正点)
  5. Update statistics

- [ ] **Step 2: Run merge script**

```bash
python tasks/ut/scripts/migrate_manifest.py \
    --test-list tasks/ut/dataset/ut_test_list_full_20260624_173600.txt \
    --old-manifest tasks/ut/dataset/manifest.json \
    --schema skills/ut/shared/manifest_schema.json \
    --output tasks/ut/dataset/manifest.json
```

Expected output: Total 33286, Passed 6411, Progress 19.26%

- [ ] **Step 3: Verify merged manifest statistics**

Check statistics field: total=33286, passed=6411, pending=26875

- [ ] **Step 4: Verify merged manifest preserves passed test fields**

Check passed test entry has preserved: `log_file`, `last_run_at`, `error_type` (修正验证)

- [ ] **Step 5: Commit merge script and result**

Commit both script and merged manifest with detailed message.

---

## Task 4: Update PROGRESS.md (子系统A)

**Files:**
- Modify: `tasks/ut/PROGRESS.md`

- [ ] **Step 1: Update statistics section**

Lines 9-14: Change total tests to 33,286, progress to 19.26%

- [ ] **Step 2: Update Skills version**

Line 22: Change `ut-test-collector` to `unit-test-collector`

- [ ] **Step 3: Add milestone**

Add row: `2026-06-26 | Documentation Cleanup + Reports Reorganization`

- [ ] **Step 4: Update Hermes Kanban Phase 3**

Change Phase 3 status from `⬜` to `✅`

- [ ] **Step 5: Update pending work**

Remove "Kanban Phase 3 验证" from pending work

- [ ] **Step 6: Update last update timestamp**

Change to `2026-06-26`

- [ ] **Step 7: Verify changes with git diff**

Check all changes applied correctly

- [ ] **Step 8: Commit PROGRESS.md update**

Commit with detailed message.

---

## Task 5: Final Verification

- [ ] **Step 1: Verify dataset directory structure**
- [ ] **Step 2: Verify test_analysis remaining files**
- [ ] **Step 3: Verify git log shows all commits**
- [ ] **Step 4: Verify manifest statistics match PROGRESS.md**
- [ ] **Step 5: Create summary commit if needed**

---

## Self-Review Checklist

**1. Spec coverage**: ✅ All subsystems (E/D/C/A) covered
**2. Placeholders**: ✅ No TBD/TODO, all code complete
**3. Type consistency**: ✅ Fields consistent (`test_node`, `status`, `error_type`)

---

**Plan complete. Ready for execution.**