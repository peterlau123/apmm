---
name: failure-handler
description: Stage 4 - Agent-driven failure analysis and fix, produces handled_tests.json
version: 3.1.0
when_to_use: Supervisor calls after Stage 3 (execute) to process failed/error tests
---

# Failure Handler (v3.1)

This is an **Agent-driven** skill. The Agent reads batch results, analyzes
failures, optionally generates and applies code fixes, then calls
generate_handled_manifest.py to produce the output.

## HARD CONTRACT (non-negotiable)

1. **Output schema is canonical.** handled_tests.json MUST be produced by
   generate_handled_manifest.py and MUST validate against
   handled_tests_schema.json. Per-test rows MUST use the same test_node
   strings from batch_results.json (join key for manifest-updater).
   Never hand-write this file.

2. **Read, do not invent.** All inputs (batch_results.json, summary.txt,
   remote pytest log) are read-only. If summary.txt is missing/empty, return
   {"next_action":"wait","reason":"no summary"}. Do NOT classify based on
   test names alone.

3. **Only failed and version error are in scope.** Other error types
   (timeout, resource, network, dependency, download_error) are classified
   as ignored by Stage 5. retriable_error is owned by Stage 2.
   Use analyze_failures.filter_processable(tests) to enforce scope.

4. **Dependency-stall classifier output is schema-validated.** The LLM helper
   at classify_dependency_stall.py validates against
   dependency_stall_schema.json. On any validation failure, returns
   verdict="unknown" - never invent a verdict.

5. **Branch safety is mandatory.** Before any git apply / git commit,
   call ensure_on_branch("2.5.1_ut_verify", vllm_repo_path) from
   skills/ut/terminal-workflow/scripts/check_vllm_branch.py.

## Input / Output

```
Input:  batch_results.json    (from Stage 3 executor)
        summary.txt           (grep PASSED/FAILED/ERROR lines)
        remote pytest log     (via agent.py, fragments only)
        test_load             (read-only, for resolved_errors/failures cache)
Output: handled_tests.json    (schema-validated delta file)
        git commits           (remote, [auto-fix] prefix, on 2.5.1_ut_verify branch)
```

## Scripts

| Script | Purpose |
|--------|---------|
| generate_handled_manifest.py | Produce handled_tests.json (HARD CONTRACT designated) |
| classify_dependency_stall.py | LLM-based timeout classifier (frozen prompt) |
| analyze_failures.py | Filter processable tests, resolve remote log paths |
| apply_patch_remote.py | Apply git patches on remote vLLM repo |

## Behavior

### What is processed

Only tests with status failed or error with error_type="version".
Other error types -> ignored by Stage 5. retriable_error -> Stage 2.

### Verification cycle

```
filter_processable -> classify -> generate_patch -> apply_patch_remote
  -> retry on remote
       -> pass => fixed_pending_verify (awaiting human review)
       -> fail => keep failed (next round may try again)
  -> max_retry exhausted => promoted to ignored by Stage 5
```

### Commit policy

- Branch: only 2.5.1_ut_verify
- Message prefix: [auto-fix] <body> (use apply_patch_remote.build_commit_message)
- Review: git log --grep=[auto-fix] 2.5.1_ut_verify

### Error classification

| Pattern | status | error_type |
|---------|--------|------------|
| FAILED | failed | assertion |
| TypeError/AttributeError (API change) | error | version |
| ModuleNotFoundError/ImportError | error | dependency |
| timeout (watchdog kill) | retriable_error | timeout |
| CUDA OOM | retriable_error | oom |
| other | error | other |

## Dependency-stall classifier (frozen prompt)

**Trigger**: batch killed by watchdog (returncode=124, error_type="timeout").
**Input**: remote log tail (~200 lines via agent.py run "tail -200 <path>").
**Output**: JSON per dependency_stall_schema.json:

```json
{"classification": "dep_stall | not_dep_stall | unknown",
 "evidence": "<log line quote>",
 "dependency_hint": "<resource name or null>"}
```

### Frozen LLM prompt (do not modify at runtime)

Prompt constant: scripts/classify_dependency_stall.py::PROMPT_TEMPLATE.
This prompt and the constant must be modified together.
See the design doc for the exact prompt text:
tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md section 5

### Decision table

| classification | final_status | ignored_reason |
|---|---|---|
| dep_stall | ignored | dependency not ready: {dep_hint or evidence} |
| unknown | ignored | classification unclear; log tail: {evidence} |
| not_dep_stall | retriable_error | - (enters retry) |

unknown -> ignored is conservative: better to skip 1 retry than waste 30 min
on a stuck HF download.

## Return format (unified)

```json
{
  "stats": {"passed": 3, "fixed_pending_verify": 2, "failed": 1, "ignored": 1, "pending": 0},
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
```

## Pre/Post conditions

| Type | Condition |
|------|-----------|
| **Pre** | batch_results.json exists (from Stage 3) |
| **Pre** | summary.txt exists (from Stage 3) |
| **Pre** | Bastion connected (for remote log access) |
| **Pre** | vLLM repo on branch 2.5.1_ut_verify (for auto-fix) |
| **Post** | handled_tests.json written (schema-validated) |
| **Post** | Supervisor continues to Stage 5 (update_batch_state) |

## Prohibited

- Do not fabricate handled_tests.json or error classifications
- Do not modify test_load or manifest (Stage 5 owns writes)
- Do not retry tests (Stage 2 owns retry selection)
- Do not send Feishu notifications (Supervisor handles)
- Do not auto-proceed without branch safety check
- Do not write scripts to repo root (work in run_dir)

---

*Updated: 2026-07-13*
*Version: 3.1.0*
