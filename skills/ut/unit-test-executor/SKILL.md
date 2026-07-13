---
name: unit-test-executor
description: Stage 3 - execute pytest batch remotely, generate batch_results.json
version: 5.1.0
when_to_use: Supervisor calls to execute a batch of tests on remote GPU host
---

# Unit Test Executor (v5.1)

## HARD CONTRACT (non-negotiable)

1. **Output schema is canonical.** atch_results.json MUST be produced by
   execute_batch.py and MUST validate against atch_results_schema.json.
   Never hand-write this file.

2. **Run the script, do not narrate.** The only sanctioned way to run a batch:
   `
   python skills/ut/unit-test-executor/scripts/execute_batch.py \
       --batch-config <path> --workflow-state <path>
   `
   If you cannot run it (sandbox/bastion error), return
   {"next_action":"wait","reason":...}. Do NOT fabricate results.

3. **Remote log is the source of truth.** Every test status comes from parsing
   the remote pytest log at <ut_logs_dir>/<batch_id>/pytest_<batch_id>.log.
   If log is missing/unparseable, classify as 
etriable_error/	imeout.

4. **All timestamps are UTC ISO 8601 with Z suffix.**
   Pattern: ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$

5. **No retry inside the Worker.** 
etriable_error/error is a signal to
   Stage 2 (batch-selector). Do NOT loop, re-run, or mutate 
etry_count.

## Input / Output

`
Input:  batch_config.json    (from Stage 2 batch-selector)
        workflow_state.json   (for paths, remote config)
Output: batch_results.json    (schema-validated, written to batch_dir)
        summary.txt           (local copy of grep'd PASSED/FAILED/ERROR lines)
`

## Script

skills/ut/unit-test-executor/scripts/execute_batch.py (self-contained, ~50KB)

## Behavior

### Remote execution

1. Read batch_config.json -> get test list
2. Read workflow_state.json -> get remote_server, docker_container, vllm_dir, ut_logs_dir
3. Build pytest command with watchdog (idle-timeout + wall-clock fallback)
4. Execute remotely via gent.py -p <profile> run --timeout <T> "..."
5. All stdout/stderr redirected to single remote file: <ut_logs_dir>/<batch_id>/pytest_<batch_id>.log
6. After pytest returns: grep -E '(PASSED|FAILED|ERROR|SKIPPED|__WATCHDOG__)' -> local summary.txt

### Error classification

| Pattern | status | error_type |
|---------|--------|------------|
| PASSED (no FAILED on same fragment) | passed | None |
| 	orch.cuda.OutOfMemoryError / CUDA out of memory | 
etriable_error | oom |
| pytest-timeout (+ Timeout >Ns + / Failed: Timeout) | 
etriable_error | timeout |
| ERROR collecting / ImportError / ModuleNotFound | error | collection |
| FAILED | ailed | assertion |
| anything else | error | other |

OOM and timeout are **transient** -> re-runnable by Stage 2 in a later batch.

### Bastion disconnect

When gent.py raises ConnectionError:
1. Mark astion.status = "disconnected" in workflow_state.json
2. Return {"next_action": "wait", "reason": ...}
3. Do NOT write batch_results.json

### batch_results.json structure

`json
{
  "batch_id": "batch_20260712_143000",
  "started_at": "2026-07-12T14:30:00Z",
  "finished_at": "2026-07-12T14:35:00Z",
  "exit_code": 0,
  "remote_log": {
    "host": "t_h20",
    "container": "v0.13.0_torch2.5.1_compile",
    "raw_log_path": "/gpfs/.../ut_logs/<batch_id>/pytest_<batch_id>.log",
    "size_bytes": 4242,
    "captured_at": "2026-06-20T12:34:56Z"
  },
  "tests": [
    {"test_id": 1, "test_node": "tests/test_load.py::test_llama", "status": "passed", "error_type": null}
  ],
  "statistics": {"passed": 6, "failed": 1, "error": 1, "retriable_error": 0}
}
`

Schema: skills/ut/unit-test-executor/batch_results_schema.json

### Type-B fabrication backstop

Stage 5 (manifest-updater) independently stat-checks the remote log before
consuming batch_results. If the log doesn't exist or size disagrees,
batch_results is rejected. Do NOT fabricate log paths.

## Return format (unified)

`json
{
  "stats": {"passed": 6, "failed": 1, "error": 1, "ignored": 0, "pending": 0},
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
`

## Pre/Post conditions

| Type | Condition |
|------|-----------|
| **Pre** | batch_config.json exists (from Stage 2) |
| **Pre** | Bastion connected (agent.py ping succeeds) |
| **Pre** | Remote container running |
| **Post** | batch_results.json written (schema-validated) |
| **Post** | summary.txt written (local grep output) |
| **Post** | Supervisor continues to Stage 4 (failure-handler) |

## Prohibited

- Do not fabricate batch_results.json or log paths
- Do not retry tests inside the Worker (Stage 2 owns retry)
- Do not modify test_load or manifest (read-only for this stage)
- Do not send notifications (Supervisor handles)

---

*Updated: 2026-07-13*
*Version: 5.1.0*
