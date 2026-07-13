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
   handled_tests_schema.json. Per-test rows MUST use the same 	est_node
   strings from atch_results.json (join key for manifest-updater).
   Never hand-write this file.

2. **Read, do not invent.** All inputs (atch_results.json, summary.txt,
   remote pytest log) are read-only. If summary.txt is missing/empty, return
   {"next_action":"wait","reason":"no summary"}. Do NOT classify based on
   test names alone.

3. **Only ailed and ersion error are in scope.** Other error types
   (timeout, resource, network, dependency, download_error) are classified
   as ignored by Stage 5. 
etriable_error is owned by Stage 2.
   Use nalyze_failures.filter_processable(tests) to enforce scope.

4. **Dependency-stall classifier output is schema-validated.** The LLM helper
   at classify_dependency_stall.py validates against
   dependency_stall_schema.json. On any validation failure, returns
   erdict="unknown" - never invent a verdict.

5. **Branch safety is mandatory.** Before any git apply / git commit,
   call ensure_on_branch("2.5.1_ut_verify", vllm_repo_path) from
   skills/ut/terminal-workflow/scripts/check_vllm_branch.py.

## Input / Output

`
Input:  batch_results.json    (from Stage 3 executor)
        summary.txt           (grep'd PASSED/FAILED/ERROR lines)
        remote pytest log     (via agent.py, fragments only)
        test_load             (read-only, for resolved_errors/failures cache)
Output: handled_tests.json    (schema-validated delta file)
        git commits           (remote, [auto-fix] prefix, on 2.5.1_ut_verify branch)
`

## Scripts

| Script | Purpose |
|--------|---------|
| generate_handled_manifest.py | Produce handled_tests.json (HARD CONTRACT designated) |
| classify_dependency_stall.py | LLM-based timeout classifier (frozen prompt) |
| nalyze_failures.py | Filter processable tests, resolve remote log paths |
| pply_patch_remote.py | Apply git patches on remote vLLM repo |

## Behavior

### What is processed

Only tests with status ailed or error with error_type="version".
Other error types -> ignored by Stage 5. 
etriable_error -> Stage 2.

### Verification cycle

`
filter_processable -> classify -> generate_patch -> apply_patch_remote
  -> retry on remote
       -> pass => fixed_pending_verify (awaiting human review)
       -> fail => keep failed (next round may try again)
  -> max_retry exhausted => promoted to ignored by Stage 5
`

### Commit policy

- Branch: only 2.5.1_ut_verify
- Message prefix: [auto-fix] <body> (use pply_patch_remote.build_commit_message)
- Review: git log --grep='[auto-fix]' 2.5.1_ut_verify

### Error classification

| Pattern | status | error_type |
|---------|--------|------------|
| FAILED | ailed | assertion |
| TypeError/AttributeError (API change) | error | version |
| ModuleNotFoundError/ImportError | error | dependency |
| timeout (watchdog kill) | 
etriable_error | timeout |
| CUDA OOM | 
etriable_error | oom |
| other | error | other |

## §X. Dependency-stall classifier (frozen prompt)

**Trigger**: batch killed by watchdog (returncode=124, error_type="timeout").
**Input**: remote log tail (~200 lines via gent.py run "tail -200 <path>").
**Output**: JSON per dependency_stall_schema.json:

`json
{"classification": "dep_stall | not_dep_stall | unknown",
 "evidence": "<log line quote>",
 "dependency_hint": "<resource name or null>"}
`

### Frozen LLM prompt (do not modify at runtime)

`
以下是一个 pytest batch 因 idle/wall-clock timeout 被 kill 后的日志末尾内容。

判断这次 timeout 的真因，分类为以下三者之一：

1. "dep_stall" - 因「依赖资源未就绪」而 hang，典型证据：
   - HuggingFace 模型下载中（"Downloading", "Fetching", URL 含 huggingface.co）
   - pip install 中（"Collecting", "Downloading .whl"）
   - HF cache miss / auth token 等待
   - 任何形式的「正在等待网络资源到位」

2. "not_dep_stall" - 看不到上述迹象，更像是：
   - 测试代码本身 hang / 死锁
   - GPU OOM / CUDA error
   - SSH transport drop（log 末尾正常 PASSED 后无新内容）
   - 其它非依赖资源类的卡死

3. "unknown" - 看不清属于哪类；判不准时优先选这个（保守）。

输出严格 JSON（无 markdown fence、无前后文）：
{
  "classification": "<dep_stall | not_dep_stall | unknown>",
  "evidence": "<引用 log 里一行原文作为依据>",
  "dependency_hint": "<具体资源名，如 'meta-llama/Llama-3.2-1B' 或 'mteb' 包名；非 dep_stall 时为 null>"
}

evidence 必填且必须来自 log；不允许编造或泛述。
`

Prompt constant: scripts/classify_dependency_stall.py::PROMPT_TEMPLATE.
This section and the constant must be modified together.

### Decision table

| classification | final_status | ignored_reason |
|---|---|---|
| dep_stall | ignored | 依赖未就绪需人工处理: {dep_hint or evidence} |
| unknown | ignored | 分类不明; 末尾日志: {evidence} |
| 
ot_dep_stall | 
etriable_error | - (enters retry) |

unknown -> ignored is conservative: better to skip 1 retry than waste 30 min
on a stuck HF download.

## Return format (unified)

`json
{
  "stats": {"passed": 3, "fixed_pending_verify": 2, "failed": 1, "ignored": 1, "pending": 0},
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
`

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
