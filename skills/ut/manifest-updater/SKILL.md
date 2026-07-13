---
name: manifest-updater
description: Stage 5 - update test_load per-batch (v5 merge), sync to manifest post-loop
version: 4.0.0
when_to_use: Per-batch after Stage 4 (failure-handler); post-loop when test_load pending==0
---

# Manifest Updater (v4.0)

## Data Flow

```
Per-batch (Stage 4.5):
  update_batch_state.py (skills/ut/shared/)
    -> merge_batch_results(test_load, batch_results, handled_tests)
    -> writes test_load (working dataset)
    -> updates workflow_state.json (batch -> completed)

Post-loop (when test_load pending == 0):
  update_manifest_from_test_load.py
    -> copies all fields from test_load to manifest.json (master record)
    -> uses calculate_statistics for manifest statistics

Manual/debug:
  update_status.py --workflow-state <path>  (or --manifest-path)
    -> CLI: --report, --daily-report, --recalc-stats, --single, --batch
```

## HARD CONTRACT (non-negotiable)

1. **test_load is the per-batch write target.** Each batch update goes to
   test_load via update_batch_state.py, which calls merge_batch_results.
   manifest.json is only written post-loop by update_manifest_from_test_load.py.
   Never write manifest.json during the batch loop.

2. **Run the stat audit, do not skip it.** Before consuming
   batch_results.tests, update_from_workflow_state() runs
   audit_batch_results() which stat-checks the remote pytest log. If
   the audit returns {"error":"audit_failed","reason":...}, the test_load
   MUST NOT be mutated. This is the Type-B fabrication backstop.

3. **batch_results.json is read-only here.** Stage 5 never re-classifies
   tests, never re-runs pytest, never edits batch_results.json. The only
   permitted mutation is to test_load (per-batch) or manifest.json (post-loop).

4. **handled_tests.json overrides batch_results.json.** When both
   files exist for a batch, handled_tests.tests[*] is applied AFTER the
   batch_results merge so a fixer-confirmed verdict (e.g. ignored with
   ignore_reason) wins.

5. **Statistics are recomputed, never copied.** After the merge,
   calculate_statistics() recounts from tests[*].status. Do NOT copy
   batch_results.statistics into test_load.statistics.

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
| update_batch_state.py | skills/ut/shared/ | Per-batch: merge to test_load + update workflow_state |
| update_manifest_from_test_load.py | skills/ut/manifest-updater/scripts/ | Post-loop: sync test_load -> manifest.json |
| update_status.py | skills/ut/manifest-updater/scripts/ | Manual/debug CLI + library (merge_batch_results, audit, calculate_statistics) |
| generate_daily_reports.py | skills/ut/manifest-updater/scripts/ | Utility: daily report generation |
| merge_phases.py | skills/ut/manifest-updater/scripts/ | Utility: merge Phase 1 + Phase 2 manifests |

## Input / Output

### Per-batch (update_batch_state.py)

```
Input:  batch_results.json    (from Stage 3)
        handled_tests.json   (from Stage 4, optional)
        test_load            (working dataset, via workflow_state paths.test_load)
Output: test_load            (updated with v5 merge)
        workflow_state.json  (batch status -> completed)
```

### Post-loop (update_manifest_from_test_load.py)

```
Input:  test_load_xxx.json   (completed working dataset, pending == 0)
        manifest.json        (master record)
Output: manifest.json        (updated with all test_load results + v5 fields)
```

## Return format (unified)

```json
{
  "stats": {"passed": 500, "failed": 50, "error": 0, "ignored": 16, "pending": 12499},
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
```

## Pre/Post conditions

| Type | Condition |
|------|-----------|
| **Pre (per-batch)** | batch_results.json exists |
| **Pre (per-batch)** | test_load exists in workflow_state |
| **Pre (post-loop)** | test_load pending == 0 |
| **Post (per-batch)** | test_load updated (v5 merge) |
| **Post (per-batch)** | workflow_state batch -> completed |
| **Post (post-loop)** | manifest.json updated with all results |

## Prohibited

- Do not write manifest.json during the batch loop (only post-loop)
- Do not skip the Type-B stat audit
- Do not copy batch_results.statistics (always recompute)
- Do not re-classify tests (Stage 4 owns classification)
- Do not re-run pytest (Stage 3 owns execution)

## Related

- [manifest_schema.json](../shared/manifest_schema.json) - Output schema
- [update_status.py](scripts/update_status.py) - merge_batch_results + audit + CLI
- [update_manifest_from_test_load.py](scripts/update_manifest_from_test_load.py) - Post-loop sync
- [update_batch_state.py](../shared/update_batch_state.py) - Per-batch update

---

*Updated: 2026-07-13*
*Version: 4.0.0*
