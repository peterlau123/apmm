---
name: manifest-updater
description: Stage 5 - update test_load per-batch (v5 merge), sync to manifest post-loop
version: 4.1.0
when_to_use: Per-batch after Stage 4 (failure-handler); post-loop when test_load pending==0
---

# Manifest Updater (v4.0)

## Data Flow

```
Per-batch - linear/kanban mode:
  update_test_load.py --workflow-state <path>
    -> update_from_workflow_state()
    -> audit_batch_results() (Type-B stat check on remote log)
    -> merge_batch_results(test_load, batch_results, handled_tests)
    -> writes test_load + validates schema

Per-batch - two-phase mode:
  update_test_load_two_phase.py --workflow-state --batch-id --batch-results
    -> merge_batch_results(test_load, batch_results, handled_tests)
    -> calculate_statistics(test_load) (recompute, never copy)
    -> writes test_load (NO stat audit - two-phase uses checkpoint verification instead)
    -> updates workflow_state.json (batch -> completed)

  verify_batch_checkpoint.py --workflow-state --batch-id
    -> reads test_load from workflow_state paths.test_load
    -> checks any test has last_batch_id == batch_id with non-pending status
    -> exit 0 = verified, 1 = failed, 2 = error

Post-loop (when test_load pending == 0):
  update_manifest_from_test_load.py
    -> copies all fields from test_load to manifest.json (master record)
    -> uses calculate_statistics for manifest statistics

Manual/debug:
  update_test_load.py --report / --daily-report / --recalc-stats / --single / --batch
```

## HARD CONTRACT (non-negotiable)

1. **test_load is the per-batch write target.** Each batch update goes to
   test_load. manifest.json is only written post-loop by
   update_manifest_from_test_load.py. Never write manifest.json during
   the batch loop.

2. **Stat audit in linear/kanban mode.** update_from_workflow_state() runs
   audit_batch_results() which stat-checks the remote pytest log before
   consuming batch_results. If audit returns {"error":"audit_failed"},
   test_load MUST NOT be mutated. Two-phase mode uses
   verify_batch_checkpoint.py instead of stat audit.

3. **batch_results.json is read-only.** Stage 5 never re-classifies tests,
   never re-runs pytest, never edits batch_results.json. The only permitted
   mutation is to test_load (per-batch) or manifest.json (post-loop).

4. **handled_tests.json overrides batch_results.json.** Applied AFTER
   batch_results merge so fixer-confirmed verdicts (e.g. ignored with
   ignore_reason) win.

5. **Statistics are recomputed, never copied.** calculate_statistics()
   recounts from tests[*].status. Do NOT copy batch_results.statistics.

## v5 merge logic (merge_batch_results)

For each test in batch_results['tests']:
- Set last_batch_id
- Copy error_type, error_message, log_file, duration_ms, exit_code, run_at
- If status in {failed, retriable_error, error}: retry_count += 1
- If retriable_error AND retry_count >= max_retry: -> ignored with ignore_reason
- Otherwise: set new status

For each test in handled_tests['tests'] (applied AFTER batch_results):
- Override status (from 'status' or 'final_status' field)
- Set ignore_reason if present
- Copy commit, errors[], failures[] if present

## Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| update_test_load.py | manifest-updater/scripts/ | Linear/kanban per-batch (with stat audit) + manual CLI + shared library |
| update_test_load_two_phase.py | shared/ | Two-phase per-batch (no stat audit) + workflow_state update |
| verify_batch_checkpoint.py | manifest-updater/scripts/ | Two-phase checkpoint: verify test_load was updated for a batch |
| update_manifest_from_test_load.py | manifest-updater/scripts/ | Post-loop: sync test_load -> manifest.json |
| generate_daily_reports.py | manifest-updater/scripts/ | Utility: daily report (deprecated, use --daily-report flag) |
| merge_phases.py | manifest-updater/scripts/ | Utility: one-time merge Phase 1+2 manifests |

## Input / Output

### Per-batch

```
Input:  batch_results.json    (from Stage 3)
        handled_tests.json   (from Stage 4, optional)
        test_load            (via workflow_state paths.test_load)
Output: test_load            (updated with v5 merge)
        workflow_state.json  (batch -> completed, two-phase only)
```

### Post-loop

```
Input:  test_load_xxx.json   (pending == 0)
        manifest.json        (master record)
Output: manifest.json        (updated with all results + v5 fields)
```

## Pre/Post conditions

| Type | Condition |
|------|-----------|
| **Pre (per-batch)** | batch_results.json exists |
| **Pre (per-batch)** | test_load exists in workflow_state |
| **Pre (post-loop)** | test_load pending == 0 |
| **Post (per-batch)** | test_load updated (v5 merge) |
| **Post (post-loop)** | manifest.json updated with all results |

## Prohibited

- Do not write manifest.json during the batch loop (only post-loop)
- Do not copy batch_results.statistics (always recompute)
- Do not re-classify tests (Stage 4 owns classification)
- Do not re-run pytest (Stage 3 owns execution)

## Related

- [manifest_schema.json](../shared/manifest_schema.json)
- [update_test_load.py](scripts/update_test_load.py) - merge_batch_results + stat audit + CLI (linear/kanban)
- [update_test_load_two_phase.py](../shared/update_test_load_two_phase.py) - Two-phase per-batch (no stat audit)
- [verify_batch_checkpoint.py](scripts/verify_batch_checkpoint.py) - Two-phase checkpoint verification
- [update_manifest_from_test_load.py](scripts/update_manifest_from_test_load.py) - Post-loop sync

---

*Updated: 2026-07-13*
*Version: 4.1.0*
