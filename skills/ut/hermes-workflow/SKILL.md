---
name: hermes-workflow
description: "Hermes-channel supervisor for the UT workflow. A long-running ut-supervisor Hermes Agent subscribes to Feishu, owns the full workflow state machine (running/paused/waiting_otp/completed/stopped/failed), auto-manages the Bastion daemon with OTP recovery, and drives the shared loop via workflow-loop-core."
version: 5.1.0
when_to_use: "Loaded into the ut-supervisor profile on Feishu trigger ('跑 L1'..'跑 L4' / '正式生产' / legacy '跑 ut workflow'). Production unattended channel - for terminal debugging use terminal-workflow."
---

# hermes-workflow (v5)

## HARD CONTRACT (5 rules, non-negotiable)

1. **Output schemas canonical per Stage.** Stage3 -> `batch_results.json` (execute_batch.py, schema `unit-test-executor/batch_results_schema.json`); Stage4 -> `handled_tests.json` (generate_handled_manifest.py); Stage5 mutates `test_load` (update_test_load.py). Each REJECTS hand-rolled payloads via jsonschema + (Stage5) remote `stat` audit.
2. **State machine values fixed.** `workflow.status ∈ {running, paused, waiting_otp, completed, stopped, failed}`. No invented states. Transitions only - direct writes to workflow_state.json forbidden.
3. **Bastion single-tenant.** Only `BastionManager` owns daemon lifecycle. On `ConnectionError`, stage returns `{"next_action":"wait","reason":...}`; supervisor reconnect loop handles it. No ad-hoc `agent.py login`/restarts from a stage.
4. **Stages via canonical scripts.** No inline pytest, no hand-rolled SSH, no LLM-fabricated output. On script failure, fail loud (write run log) - never synthesize Stage output.
5. **All timestamps UTC ISO 8601 Z.** Pattern `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$`. Use `datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")`.

## Data Flow: test_load = working dataset, manifest = master record

test_load_xxx.json is the working dataset (Stages 2-4.5 read/write it). manifest.json is the master record, updated once when `pending==0`. Avoids polluting manifest with intermediate failure states.

```
Init: collect (manifest from test_list or manifest_source)
  -> Stage1: generate test_load (generate_test_load.py, extract N from manifest)
  -> [Loop] Stage2 select_batch -> Stage3 execute (remote pytest)
          -> Stage4 handle_failures -> Stage4.5 update_test_load
          (loop until test_load pending==0)
  -> Stage5: sync test_load -> manifest (update_manifest_from_test_load.py)
```

- Stage2 (generate_batch.py): reads test_load, picks next pending batch; normal tests first, distributed when none remain.
- Stage3 (execute_batch.py): remote pytest. Normal: 1 GPU/test. Distributed: torchrun, gpu_per_test GPUs/test.
- Stage4 (failure-handler): classify failures -> handled_tests.json (retry/ignore/fix).
- Stage4.5 (update_test_load_two_phase.py): v5 merge (retry_count++, retriable_error->ignored, handled overrides) + workflow_state batch->completed.
- Stage5 (update_manifest_from_test_load.py): sync test_load -> manifest (requires pending==0).

## Role

Runs in `ut-supervisor` Hermes Agent profile (`systemctl status hermes-agent@ut-supervisor`). **Only** Feishu subscriber - 3 Kanban Gateways don't subscribe. Feishu 双向: subscribes `apmm-ut` for commands+OTP, posts progress/OTP/completion cards. Owns Bastion daemon (heartbeat, OTP recovery) reused by all Workers. Owns full state machine. Diff from terminal-workflow: that has no state machine, no paused/waiting_otp, Bastion human-maintained.

## Architecture

```
User <-> Feishu <-> ut-supervisor (Hermes Agent)
                    |-- [linear, kanban.enabled=false] drives Stage 2-5 directly via Worker SKILLs
                    `-- [kanban, kanban.enabled=true]  polls Gateway Workers (ut-orchestrator/executor/fixer), never touches test_load
                    Bastion daemon (agent.py SSH -> t_h20 -> remote GPU)
```

## Startup (script-driven, §3.A)

```
A1. validate_required_config(yaml) - test_list or manifest_source; remote_server; (kanban) check_gateways_alive all active. Fail -> red card -> exit.
A2. create_run_dir.py --mode hermes -> runs/ut-{ts}/, copies yaml, structured params.
A3. Feishu param card (5 editable fields: test_list_path, manifest_source, execution_strategy, test_load.count, batch_size, max_retry, resume_from) -> user confirm or KEY=VAL.
A4. prepare_run_data.py --mode hermes -> manifest.json + workflow_state.json + test_load.
A5. Bastion bring-up + start_heartbeat. daemon unavailable -> waiting_otp (§OTP). Linear: if unreachable after OTP timeout -> red card + STOP (don't enter loop).
A5b. Final confirmation card (linear only): run summary -> "confirm start" / "cancel".
A6. Strategy: single-phase -> loop_core.run(); two-phase -> auto_run_batches_two_phase.py (Phase1) -> two-phase-handler (Phase2).
A7. Post-loop (pending==0): update_manifest_from_test_load.py sync test_load -> manifest.
```

**Startup interlock:** idle -> proceed A1; running/paused/waiting_otp -> red card "already running (status=X), stop/pause first".

### Tier -> yaml mapping (§3.C)

| Intent | yaml | test_list | ETA |
|--------|------|-----------|-----|
| start_l1 | `tests/ut/integration/fixtures/workflow.l1.yaml` | l1_smoke_list.txt | <1m |
| start_l2 | `workflow.l2.yaml` | mini_test_list.txt | ~3m |
| start_l3 | `workflow.l3.yaml` | l3_fast_subset.txt | ~15m |
| start_l4 | `workflow.l4.yaml` | l4_test_list_v2.txt | ~60m |
| start_production | `tasks/ut/deployment/production/config/workflow.yaml` | (from yaml) | h-d |

All linear mode (kanban.enabled from yaml, default false). `mode`/`eta` for card display only.

### Intent recognition (2-layer, §3)

- **Layer1** `parse_command(text)` regex: otp/otp_with_id/stop/pause/resume/change_config -> dispatch to state machine, skip startup.
- **Layer1 miss -> Layer2** `classify_intent_llm(text)` (Agent's own LLM produces JSON, this parses/validates): intent in {start_l1..l4, start_production, change_config, unknown}. No external LLM invoker.
- `unknown` (incl. bare "跑 ut workflow" without tier suffix - conservative gate to avoid misfiring production) -> help card listing legal triggers, end round.

## Tooling: `ut_runner.py` + `bastion_manager`

```python
from ut_runner import (
    parse_command, classify_intent_llm, Command,
    init_or_resume, validate_required_config, check_gateways_alive,
    get_execute_config, apply_pending_config, refresh_test_load_stats,
    check_stop_conditions, send_feishu_card,
)
from bastion_manager import (BastionManager, otp_resend_delay, otp_should_at_user)
```

BastionManager methods: `ensure_connected`, `start_heartbeat`, `stop_heartbeat`, `mark_disconnected`, `mark_connected`, `request_otp`. Bring-up is in runner setup path (constructs BastionManager, sets heartbeat interval, calls ensure_connected).

## Callbacks (-> `loop_core.run`)

| Callback | Behavior |
|----------|----------|
| `handle_checkpoint(state, test_load)` | `refresh_test_load_stats()` -> Feishu progress card -> drain+process user commands |
| `handle_bastion_disconnect(reason)` | -> `waiting_otp` -> progressive OTP resend (§OTP); on valid OTP: sync daemon restart -> `mark_connected` -> `running`; on "结束": `stopped` |
| `check_user_commands()` | 2-layer intent on every new Feishu msg (Layer1 regex -> Layer2 LLM). start_*/change_config queued for startup hook (idle only); unknown -> help card |
| `check_terminal_conditions(state, test_load)` | `check_stop_conditions()` -> `(done, reason, status)`, status in {completed, stopped, failed} |

## State Machine (§5/§8)

States: `{running, paused, waiting_otp, completed, stopped, failed}`. (`reconnecting` removed - OTP restart completes synchronously inside waiting_otp.)

| Current | pause | resume | stop | change_cfg | OTP |
|---------|-------|--------|------|------------|-----|
| running | ->paused | ignore | ->stopped | ->paused (store pending_config) | ignore |
| paused | ignore | ->running (apply pending_config) | ->stopped | update pending_config | ignore |
| waiting_otp | ignore | ignore | ->stopped | ignore | sync restart -> running (fail: stay waiting_otp) |
| terminal | ignore | ignore | ignore | ignore | ignore |

- **Priority:** stop > pause > change_config > resume
- **Timing:** checked once per round, after Stage5, before progress card (remote pytest can't pause mid-run).
- **Daemon restart failure:** stay `waiting_otp`, rewrite card "daemon 重启连续失败 N 次，请人工介入". NO "3 failures -> failed" path. Exits waiting_otp only via successful restart or "结束".
- **Terminal:** completed (pending==0) / stopped (user "结束") / failed (startup-time validation/config errors only).

## OTP Resend (§7)

```
attempt 1 -> 5min, 2 -> 15min, 3 -> 30min(@user), 4+ -> 60min capped (@user)
delays + @user decision from bastion module (otp_resend_delay/otp_should_at_user), don't hardcode.
No timeout->failed path.
```

## Resume (§9, `init_or_resume(resume_from=<run_dir>)`)

| Prior state | Resume behavior |
|-------------|-----------------|
| running | -> running, continue from current_stage (crash recovery) |
| paused | apply_pending_config() -> running |
| waiting_otp | restart OTP flow from attempt 1 |
| stopped | refuse: "该 run 已被停止，请新建" |
| completed | refuse: "该 run 已完成，请新建" |
| failed | re-validate (daemon/config) -> reset running |

Input: workflow_state.json + test_load_xxx.json (NOT manifest.json).

## pending_config (§10)

"改参数 key=value" -> `parse_command` extracts **whitelisted** keys only (`batch_size`, `pytest_args`, `max_retry_per_test`, `timeout`); others ignored with Feishu hint. Stashed under `state["pending_config"]`.

- Only whitelist keys; `{}` = paused without param change; not written back to workflow.yaml (temp, this run only).
- "继续": `apply_pending_config()` merges into config, clears, bumps last_update (no-op when empty).
- "结束": discard, clear. Paused card shows pending_config for user confirm.

## Completion (§15)

`trigger_intent` stored in workflow_state.json at startup. On terminal state, read it to route:

- **Tier (start_l1..l4, §10.1):** run `check_expected.py --run-dir <run_dir> --expected tests/ut/integration/fixtures/L{n}_expected.json --output-card-json <run_dir>/check_result.json`. exit 0=PASS(green,assertion summary)/1=FAIL(red,failed hard asserts,capped 8)/2=ERROR(expected file parse). -> `feishu.send_tier_completion_card(verdict, tier, run_dir)`.
- **Production (start_production/legacy, §10.2):** no check_expected. plain completion card (`send_feishu_card("complete",...)`, green with passed/failed/error/pending) + `git log master..<branch> --oneline` auto-fix summary if applicable.

Both: write final manifest + workflow_state.json (status=completed), `bastion.stop_heartbeat()`. No auto-archive; gateways/batch dirs left untouched.

## Workflow-level Retry (整批重跑)

After workflow stops (completed/user-stop/error-threshold), re-run failed/error batches:

- **Input:** workflow_state.json + test_load_xxx.json (NOT manifest.json)
- **SKILL:** `two-phase-handler` (Phase2 Stage1 stats + Stage2 retry w/ human decision)
- **Trigger:** Feishu "重跑失败的batch" / "retry failed" -> supervisor calls two-phase-handler
- **Doc:** `skills/ut/ut_common/two-phase-handler/SKILL.md`

## Pitfalls (real incidents, §11)

1. **`agent.py serve` must be background.** Foreground via Hermes `terminal` tool hits 180s timeout -> SIGKILL mid-handshake -> half-dead daemon (ping OK, run hangs "Socket is closed"). Use `terminal(background=True,...)`; `agent.py -p t_h20 stop` first if stale; verify with 2 round-trip `run` >=90s apart. Applies to initial bring-up AND OTP recovery.
2. **Trust-but-verify Stage3 (anti-fabrication).** A worker can fabricate batch_results.json without running pytest (2026-06-22 incident ut-20260621-234651: fake stats, fake NCCL error, out-of-band Feishu report). After each Stage3: validate shape (status vs exit_code+duration; `duration_seconds:null`+`status passed/failed` = suspect; empty/relative log_path = suspect); `agent.py run "ls -la <log_path>"` (missing = fabricated -> stop, mark `invalidated` not paused, red card); cross-check `ps -ef|grep pytest` + `find ut_logs -mmin -60`. If fabricated: `mv test_load{,.fabricated.bak}`, `mv <batch_dir>{,.fabricated.bak}`, write INVALID.md, red card, do NOT resume (test_load poisoned).
3. **Workers must not send Feishu out-of-band.** Only supervisor talks to Feishu. Incident: worker wrote a script calling open.feishu.cn directly with a token from `~/.claude/skills/feishu-webhook-skill/`. If delivery seen in non-supervisor chat referring to a run id -> exfiltration event, log + tighten Worker SKILLs.
4. **Stale monitor cron outliving invalidated runs.** On invalidation: `hermes -p <profile> cron remove <job_id>` for every monitor cron (e.g. `ut-resume-monitor-<run_id>`) created for that run.

## 硬性约束 (不可违反)

- **Supervisor 逐 stage 调度:** 调度 Worker -> 检查 STAGE COMPLETED 输出 -> 检查 workflow_state.json -> 状态报告 -> 决定下一步。❌ 批量调度/循环自动化/跳过状态检查。
- **Worker 必须更新状态:** batch-selector -> `batches[id].status=='generated'`; unit-test-executor -> `=='completed'`。未更新则 Supervisor 补救更新。

## Scripts

- `scripts/orchestrator_round.py` - Kanban orchestrator round (Stage5 then Stage2, single test_load writer per round)
- `scripts/kanban_task_creator.py` - Kanban task creation
- `scripts/start_supervisor.py` - Supervisor entry point
- `scripts/refresh_profile.py` - Profile config refresh

## References

- [incident-archival.md](references/incident-archival.md)
- [kanban-operations.md](references/kanban-operations.md)
- [profile-config-audit.md](references/profile-config-audit.md)
- [run-invalidation-checklist.md](references/run-invalidation-checklist.md)
- [stalled-run-recovery.md](references/stalled-run-recovery.md)
- [verify-before-resume.md](references/verify-before-resume.md)

## Related

- [terminal-workflow](../terminal-workflow/SKILL.md) - Linear-mode terminal channel
- [workflow-loop-core](../workflow-loop-core/SKILL.md) - Shared loop body
- [two-phase-handler](../ut_common/two-phase-handler/SKILL.md) - Phase 2 retry
