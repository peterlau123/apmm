# L4 run cancelled by user 2026-06-23 ~23:05

## Reason
`skills/ut/unit-test-executor/scripts/execute_batch.py` lines 285 & 323 use
`sudo docker exec` (no `-n` flag). Remote `infra@t_h20` is not in docker group,
so sudo prompts for a password it cannot read on a non-tty SSH channel and
exits 2. pytest never started, but execute_batch.py wrote a fake all-error
`batch_results.json` (3 tests × duration_ms=0, started→finished in 1 second,
remote log path does not exist).

## Evidence
- `batch_results.json`: started_at=22:59:37 finished_at=22:59:38 exit_code=2
- `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260623_224000/`: does not exist on t_h20
- container `ps -ef | grep pytest`: empty (no real process)
- worker heartbeat kept reporting "running pytest" through 23:03
- only file in the batch dir touched by this run was the empty `summary.txt`

## Fix needed before next L4 attempt
Patch `execute_batch.py` line 285 and line 323:
`sudo docker exec` → `sudo -n docker exec`

Matches the pattern already documented in:
- memory pitfall #6 (Remote t_h20 sudo -n docker rule)
- skills/ut/unit-test-executor/SKILL.md (pitfall section)

## Tasks cancelled
- t_21b5f672 (executor) — archived
- t_b67ded7e  (fixer)    — archived
- t_a569b994 (continue-orchestrator) — archived
- t_28950d54 (orchestrator) — already done; left as-is
- monitor cron `d54687b0847b` — removed
- bastion daemon — left running (still good)
