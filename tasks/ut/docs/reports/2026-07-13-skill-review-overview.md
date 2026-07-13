# UT Workflow Skills Review Overview

**Review Date**: 2026-07-13
**Scope**: All 10 skills in the UT Workflow pipeline
**Status**: Skills 1-10 reviewed and fixed (F1 deferred)

---

## Data Flow Summary

```
manifest.json (master record)
    |
    v
(1) unit-test-collector --> manifest.json (from test_list.txt)
    |
    v
(2) generate_test_load --> test_load_xxx.json (working dataset)
    |
    v
+-- loop ------------------------------------------------+
| (3) batch-selector --> batch_config.json (reads test_load) |
|     |                                                    |
|     v                                                    |
| (4) unit-test-executor --> batch_results.json (remote pytest) |
|     |                                                    |
|     v                                                    |
| (5) failure-handler --> handled_tests.json (Agent judgment) |
|     |                                                    |
|     v                                                    |
| (6) manifest-updater --> test_load (v5 merge per-batch)  |
+----------------------------------------------------------+
    |
    v
(7) update_manifest_from_test_load --> manifest.json (post-loop sync)
    |
(8) two-phase-handler (Phase 2: batch retry, reads test_load)
(9) workflow-loop-core (shared loop body)
(10) terminal-workflow / hermes-workflow (Channel dispatch)
```

---

## Skills 1-5: Already Reviewed (Clean)

### (1) unit-test-collector v2.2
- Script: `init_workflow_state.py::create_manifest_from_test_list()`
- Status: CLEAN

### (2) generate_test_load (script, not skill)
- Script: `tasks/ut/scripts/generate_test_load.py`
- Status: CLEAN

### (3) batch-selector v2.3
- Script: `generate_batch.py`
- Status: CLEAN (recently fixed to use `select_batch()`)

### (4) unit-test-executor v5.1
- Script: `execute_batch.py` (~50KB)
- Status: CLEAN (most complex skill, 5-rule HARD CONTRACT)

### (5) failure-handler v3.1
- Scripts: `generate_handled_manifest.py`, `classify_dependency_stall.py`, etc.
- Status: CLEAN (Agent-driven, 5-rule HARD CONTRACT)

---

## Skill 6: manifest-updater v4.0 -> v4.1 (FIXED)

### Issues Found and Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 6.1 | P0 | Ghost filenames: SKILL.md + 6 docs referenced `update_status.py`/`update_batch_state.py` | Renamed to `update_test_load.py`/`update_test_load_two_phase.py`, updated all 16+ files |
| 6.2 | P0 | `update_from_workflow_state()` wrote to **manifest.json** not **test_load** | Fixed: now reads/writes test_load (HARD CONTRACT compliant) |
| 6.3 | P0 | `merge_batch.py::update_test_load()` had `workflow_state_path` scope bug | N/A: git-tracked version didn't have this bug |
| 6.4 | P1 | SKILL.md said two-phase has "NO audit" but script called `audit_batch_results()` | N/A: git-tracked version didn't import audit |
| 6.5 | P1 | `update_test_load_two_phase.py` didn't recompute statistics after merge | Fixed: added `calculate_statistics()` call |
| 6.6 | P1 | `verify_batch_updated` buried in `auto_run_batches_two_phase.py` (25KB) | Created standalone `verify_batch_checkpoint.py` with CLI |
| 6.7 | P1 | `calculate_statistics()` missing `retriable_error`/`fixed_pending_verify` | Fixed: added both status types to stats |
| 6.8 | P2 | `generate_daily_reports.py` duplicates `--daily-report` CLI flag | Marked deprecated in SKILL.md scripts table |
| 6.9 | P2 | `merge_phases.py` has hardcoded archive paths | Marked one-time utility in SKILL.md |

### Script Renaming

| Old Name | New Name | Location | Purpose |
|----------|----------|----------|---------|
| `update_status.py` | **`update_test_load.py`** | manifest-updater/scripts/ | Linear/kanban per-batch: stat audit + v5 merge -> test_load |
| `update_batch_state.py` | **`update_test_load_two_phase.py`** | shared/ | Two-phase per-batch: v5 merge -> test_load + workflow_state |
| (new) | **`verify_batch_checkpoint.py`** | manifest-updater/scripts/ | Two-phase checkpoint: verify test_load updated for batch |
| `update_manifest_from_test_load.py` | (unchanged) | manifest-updater/scripts/ | Post-loop: sync test_load -> manifest.json |

### Tests: 21 passed (17 stat audit + 4 v5 merge)

---

## Skill 7: two-phase-handler v1.0 (FIXED)

### Issues Found and Fixed

| # | Issue | Fix |
|---|-------|-----|
| 7.1 | Referenced ghost `update_status.py` | Updated to `update_test_load.py` |
| 7.2 | Infrastructure note missing two-phase + checkpoint script refs | Added `update_test_load_two_phase.py` and `verify_batch_checkpoint.py` |
| 7.3 | HARD CONTRACT rule 4 said "manifest.json" instead of "test_load" | Fixed: now says "test_load" |
| 7.4 | All inline code/flowchart/tables referenced `manifest.json` | Fixed: all changed to `test_load` (except schema + post-loop refs) |
| 7.5 | `verify_manifest_updated` function name inconsistent | Renamed to `verify_batch_updated` (matches standalone script) |
| 7.6 | Usage examples used `manifest_path` | Updated to `test_load_path` |

---

## Skill 8: workflow-loop-core v5.0 -> v5.1 (FIXED)

### Issues Found and Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 8.1 | P1 | Interface param `manifest_path` should be `test_load_path` | Fixed: interface table (3 rows), linear pseudocode (3 lines), kanban pseudocode (3 lines), callback signatures `handle_checkpoint(state, test_load)` + `check_terminal_conditions(state, test_load)` |
| 8.2 | P2 | Mermaid flowchart `Read[读取 state + manifest]` | Fixed: changed to `Read[读取 state + test_load]` |
| 8.3 | P2 | Kanban comment "Kanban board + manifest" | Fixed: "Kanban board + test_load" |

Remaining `manifest` references are all SKILL names (`manifest-updater`, `manifest_updater`) - correct.

---

## Skill 9: terminal-workflow v5.1 (FIXED)

### Issues Found and Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 9.1 | P1 | `handle_checkpoint(state, manifest)` and `check_terminal_conditions(state, manifest)` used `manifest` | Fixed: both signatures changed to `test_load` |
| 9.2 | P1 | `send_feishu_card(feishu, "progress", manifest, ...)` showed stale stats | Fixed: changed to `test_load` |

5 `manifest.json` references verified CORRECT (generate_test_load reads from manifest, init creates manifest, post-loop writes to manifest).

---

## Skill 10: hermes-workflow v5.1 (FIXED)

### Issues Found and Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 10.1 | P1 | HARD CONTRACT rule 1: "Stage 5 mutates `manifest.json`" | Fixed: "Stage 5 mutates `test_load`" |
| 10.2 | P1 | `handle_checkpoint(state, manifest)` + `check_terminal_conditions(state, manifest)` | Fixed: both changed to `test_load` |
| 10.3 | P1 | `refresh_manifest_stats(state_path, manifest_path)` param name | Fixed: doc shows `test_load_path` (function name kept - see Follow-up F1) |
| 10.4 | P1 | `send_feishu_card` progress + complete cards used `manifest` | Fixed: both changed to `test_load` |
| 10.5 | P2 | §6 Kanban: "never touches the manifest" + "manifest has a single writer" + "read-only from the manifest" | Fixed: all changed to `test_load` |
| 10.6 | P2 | §11.2 Pitfalls: "the manifest is poisoned" + `mv manifest.json` | Fixed: "test_load is poisoned" + `mv test_load_xxx.json` |

6 `manifest.json` references verified CORRECT (init creates manifest, generate_test_load reads from manifest, post-loop sync writes to manifest, "Write final manifest" at completion).

---

## Cross-Cutting Issues

### X1: `nul` file artifact
- Windows reserved device name file in project root
- Cannot be deleted via Python (access denied)
- Does not affect git tracking

### X2: `calculate_statistics()` duplication
- 4 independent implementations (now consolidated to use shared version from `update_test_load.py`)
- `merge_batch_manifests.py` in tasks/ut/scripts/ still has its own copy

### X3: Encoding issues
- Some SKILL.md files had GBK/UTF-8 encoding issues
- Fixed during reference updates (Python `read_text`/`write_text` with UTF-8)

---

## Files Changed Summary

- 2 files renamed (git mv): `update_status.py` -> `update_test_load.py`, `update_batch_state.py` -> `update_test_load_two_phase.py`
- 1 new file created: `verify_batch_checkpoint.py`
- 30+ files modified (SKILL.md, scripts, tests, docs) to update all references
- 21 tests passing (skills 6-7)
- 4 SKILL.md files updated (skills 7-10): manifest->test_load in callbacks, pseudocode, HARD CONTRACT

---

## Follow-up Items (Not Addressed in This Review)

### F1: Rename `refresh_manifest_stats` function (P2, deferred)

The function `refresh_manifest_stats(state_path, manifest_path)` in `skills/ut/shared/ut_runner.py`
still uses the legacy name. During the loop it receives `test_load_path`, not `manifest_path`.
The state key `manifest_stats` is also legacy.

**Recommended rename**:
- `refresh_manifest_stats` -> `refresh_test_load_stats`
- State key `manifest_stats` -> `test_load_stats`

**Affected files** (requires separate PR + test update):
- `skills/ut/shared/ut_runner.py` (function def + `check_stop_conditions`)
- `skills/ut/shared/workflow_state_manager.py` (`calculate_test_stats` parameter)
- `tests/ut/unit/test_hermes_runner_api.py` (5+ references)
- `tests/ut/unit/test_kanban_board.py` (6+ references)
- `tests/ut/unit/test_loop_core_contract.py` (1 reference)
- `tests/ut/integration/fixtures/profiles/ut-supervisor/SOUL.md` (1 reference)
- Multiple docs/plans/worklog files (historical, do not modify)

**Decision**: Doc-only fix applied this round (parameter name in SKILL.md).
Function rename deferred to avoid breaking tests without full regression.

### F2: Two-phase-handler inline code variable consistency (P3, accepted)

The 14 inline Python code blocks in `two-phase-handler/SKILL.md` are illustrative
(????), not executable. Variable naming inconsistencies within these blocks
(e.g., `get_tests_by_batch_id` parameter vs body) are acceptable for documentation
purposes. Fixed the most critical issues (import paths, manifest->test_load references).

---

*Reviewer: Claude (Default mode)*
*Review time: 2026-07-13*
