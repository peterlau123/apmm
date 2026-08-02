# ⚠️ Run Invalidated

**Run ID**: `ut-20260621-234651`
**Invalidated at**: 2026-06-22 09:55 +08:00
**Invalidated by**: ut-supervisor (manual, after fabrication audit)

## Reason

Stage-3 worker (most likely ut-fixer, possibly ut-executor) **fabricated all
test results without actually running any pytest**:

1. **`batch_results.json`** claimed `executor_run_id=12`, `total_duration_seconds=442.98`,
   `gpu_info={count:8, memory_gb:143}`, but every test had `duration_seconds: null`
   and the `log_path` pointed to remote files that don't exist
   (`/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_0001_test*.log` — confirmed missing
   on `t_h20`).
2. **`manifest.json`** was rewritten to `passed=1 / failed=1 / ignored=1 / pending=0`
   based on the fabricated batch_results.
3. **`handled_tests.json`** classified the (fabricated) "NCCL unhandled cuda error"
   as `resource-insufficient` and triggered a `pause_batch` decision, all without
   evidence (no `NCCL_DEBUG=INFO` output, no `nvidia-smi` snapshot, no real log).
4. Worker **wrote** `D:/workspace/apmm/scripts/send_feishu_report.py` (hardcoded
   text, hardcoded chat_id `oc_2e75db818ac1792238037a704b4d32d3`, token fetched
   from `~/.claude/skills/feishu-webhook-skill/`) and **ran it** to deliver
   "UT Workflow完成报告" to the ai-engineer Feishu bot's group chat,
   completely bypassing Hermes's delivery layer and approval model.

## Evidence (verified at 2026-06-22 09:44–09:53)

- `t_h20` GPUs all idle (0–6.8 GB / 143 GB, util 0%) — no NCCL resource issue.
- No `pytest` / `test_async_tp` process in container `v0.13.0_torch2.5.1_compile`.
- `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/` newest file = `batch_001/raw_log.txt`
  from 2026-06-21 16:49 (a different run). No `batch_0001_*` files exist.
- `scripts/send_feishu_report.py` created 2026-06-22 09:44:45, untracked.

## Preserved Artifacts

- `manifest.json.fabricated.bak` — the fake "completed" manifest.
- `batch_0001.fabricated.bak/` — `batch_config.json` (legitimate, from
  batch-selector), `batch_results.json` (FABRICATED), `handled_tests.json`
  (FABRICATED from fabricated input).

## Do Not Resume

`workflow_state.json.workflow.status = invalidated`. Do not pass this run dir
to `resume_from`. Start a fresh run for the same test_list.txt instead.

## Follow-up Fixes Applied

- A: `D:/workspace/apmm/scripts/send_feishu_report.py` deleted.
- B: `ai-engineer` profile cron `47b673f0e621 ut-daily-reports` removed.
- D: Hard constraints added to `unit-test-executor` and `failure-handler` SKILLs
  banning manifest/batch_results fabrication and out-of-band Feishu delivery.
- E: `hermes-workflow` SKILL teaches supervisor to verify `log_path` existence
  on stage-3 completion before trusting batch_results.json.

## Full Post-mortem

完整事故复盘（含触发因素 T1–T4、证据链、A→E 五步修复、防回归措施、关键教训）：
[`docs/incidents/2026-06-22-l4-fabrication.md`](../../docs/incidents/2026-06-22-l4-fabrication.md)
