---
name: hermes_workflow
description: Hermes-channel supervisor for the UT workflow. A long-running ut-supervisor Hermes Agent subscribes to Feishu, owns the full workflow state machine (running/paused/waiting_otp/completed/stopped/failed), auto-manages the Bastion daemon with OTP recovery, and drives the shared loop via workflow_loop_core.
version: 5.0.0
when_to_use: Loaded into the ut-supervisor profile when a Feishu trigger message ("跑 ut workflow" / "启动测试" / "开始 UT") matches, or via `hermes skill run hermes_workflow`. Production unattended channel — for OpenCode/Claude terminal debugging use ut/workflow instead.
---

# hermes_workflow (v5)

> Hermes-channel supervisor for the dual-channel UT workflow.
> Spec: `docs/superpowers/specs/2026-06-18-hermes-workflow-dual-channel-design.md`

This skill is the **生产运行通道 (production channel)** counterpart of
`ut/workflow`. Both drive the same `workflow_loop_core`; this skill supplies
the Hermes-specific callbacks: Feishu 双向消息, automatic Bastion recovery,
and the full workflow state machine.

The loop body lives in `workflow_loop_core` — this skill does **not**
re-implement stage cadence. It implements the channel-difference layer.

---

## 1. Channel & role / 通道与职责

- **Runs in** the `ut-supervisor` profile as a long-running Hermes **Agent**
  (`systemctl status hermes-agent@ut-supervisor`). It is the **only** Feishu
  subscriber in the system — the 3 Kanban Gateways do not subscribe.
- **Feishu 双向 (bidirectional):** subscribes to the `apmm-ut` group for user
  commands + OTP codes, and posts progress / OTP / completion cards.
- **Bastion 自动管理:** owns one Bastion daemon connection, heartbeat-monitored,
  recovered via Feishu OTP. All Workers (linear or Kanban) reuse this daemon.
- **Owns the full state machine** (§8): running / paused / waiting_otp /
  completed / stopped / failed, plus `pending_config`.

Difference from `ut/workflow` (terminal channel): that channel has no state
machine, no paused/waiting_otp, and Bastion is human-maintained.

---

## 2. Tooling — `hermes_runner.py`

Import the runner as a tool module (it no longer inlines stage logic):

```python
from hermes_runner import (
    parse_command,           # text → {type, payload} or None
    init_or_resume,          # (run_dir, state_path, state, iteration)
    validate_required_config,# (ok, missing_keys)
    check_gateways_alive,    # {profile: bool}  (kanban preflight + per-round)
    get_execute_config,      # flat config for execute_batch
    apply_pending_config,    # merge pending_config → config on resume
    refresh_manifest_stats,  # tally manifest statuses into state
    check_stop_conditions,   # (done, reason, status)
    orchestrator_round,      # kanban Stage5+Stage2 (used by ut-orchestrator)
    send_feishu_card,        # progress / complete / alert / paused card
)
from bastion_manager import (
    BastionManager,
    otp_resend_delay,        # attempt → minutes before next OTP resend
    otp_should_at_user,      # attempt → whether to @ the user
)
```

`BastionManager` methods used by this channel: `ensure_connected`,
`start_heartbeat`, `stop_heartbeat`, `mark_disconnected`, `mark_connected`,
`request_otp`.

> Bastion bring-up is encapsulated by the runner's setup path (it constructs
> the `BastionManager`, sets the heartbeat interval, then calls
> `ensure_connected`). Reference the *behaviour* below; do not assume a
> separate `ensure_bastion()` top-level function exists.

---

## 3. Startup sequence (§14.2)

```
1. 用户飞书发"跑 ut workflow" / "启动测试" / "开始 UT"
2. ut-supervisor Agent (Feishu subscriber) 收到消息 → 关键词匹配
3. 一次性加载：hermes_workflow + workflow_loop_core
              + 4 份 Worker SKILL（batch-selector / unit-test-executor /
                failure-handler / manifest-updater）
4. 飞书发【参数确认卡片】（蓝色），展示 5 字段：
     test_list_path, batch_size, manifest_source, kanban.enabled, resume_from
   选项："确认" / "yaml=PATH" / "resume=RUN_DIR" / "改 KEY=VALUE" / "取消"
5. 等待用户回复（5 分钟超时 → 退出）
6. "确认" → validate_required_config(cfg)
     - test_list_path 或 manifest_source 至少一个（input_filter.*）
     - config.remote_server 存在
     - kanban.enabled=true 时额外：check_gateways_alive() 三个 Gateway 全 active
     - 任一缺失 → 飞书红色错误卡片 → failed → 退出
7. init_or_resume(workflow_yaml, resume_from)
     → (run_dir, state_path, state, iteration)
8. Bastion bring-up（BastionManager + ensure_connected）
     daemon 不可用 → 进入 waiting_otp，按 §7 渐进重发节奏发 OTP 卡片
9. bastion.start_heartbeat(on_disconnect=...)
     心跳检测断联只调 mark_disconnected() 上报，不直接弹卡片 / 不切状态
10. 进入主循环 loop_core.run(stage_skills, 回调...)
```

Required-config validation maps directly to `validate_required_config`
(input_filter + remote_server) plus, in Kanban mode, a `check_gateways_alive`
gate that all 3 Gateways report `True`.

---

## 4. Channel callbacks (wired into `loop_core.run`)

`workflow_loop_core` exposes `loop_core.run(stage_skills, handle_checkpoint,
handle_bastion_disconnect, check_user_commands, check_terminal_conditions)`.
This channel supplies:

### `handle_checkpoint(state, manifest)`

Called after every successful Stage 5 (and each Kanban poll round):

1. `refresh_manifest_stats(state_path, manifest_path)` → tally into state.
2. Post a progress card via `send_feishu_card(feishu, "progress", manifest, iteration, ...)`.
3. Drain + process user commands (see `check_user_commands`).

### `handle_bastion_disconnect(reason)`

Called when an executor returns `next_action == "wait"` (Bastion loss):

1. Transition state → `waiting_otp`.
2. Progressive OTP resend per §7, using `otp_resend_delay(attempt)` for the
   delay and `otp_should_at_user(attempt)` to decide whether to @ the user;
   issue the request via `bastion.request_otp(...)`.
3. Wait for either a valid OTP (→ synchronous daemon restart →
   `mark_connected()` → `running`) or "结束" (→ `stopped`).

### `check_user_commands()`

Reads the Feishu group and parses each message with `parse_command(text)`,
returning a list of structured commands. `parse_command` recognises:
`stop` / `pause` / `resume` / `otp {code}` / `change_config {whitelisted kv}`.
(Linear `ut/workflow` returns `[]` here; this channel actually reads Feishu.)

### `check_terminal_conditions(state, manifest)`

Backed by `check_stop_conditions(state_path)` → `(done, reason, status)` with
status ∈ {`completed`, `stopped`, `failed`}.

---

## 5. State machine (§8)

States: **running / paused / waiting_otp / completed / stopped / failed**.
`reconnecting` was removed — after an OTP arrives the daemon restart completes
**synchronously inside `waiting_otp`**.

### Command matrix (§8.2)

| 当前状态 | "暂停" | "继续" | "结束" | "改参数 N" | OTP code |
|---|:---:|:---:|:---:|:---:|:---:|
| **running** | → paused | 忽略 | → stopped | → paused (存 pending_config) | 忽略 |
| **paused** | 忽略 | → running (apply pending_config) | → stopped | 更新 pending_config | 忽略 |
| **waiting_otp** | 忽略 | 忽略 | → stopped | 忽略 | 同步重启 daemon → 成功 running / 失败 维持 waiting_otp |
| **stopped / completed / failed** | 忽略 | 忽略 | 忽略 | 忽略 | 忽略 |

Non-command messages: the Agent may reply but state does **not** change.

### Command priority (§8.3)

`stop > pause > change_config > resume`

### Command timing (§8.4)

Commands are checked **once per round, after Stage 5, before the progress
card**. Remote pytest cannot be paused mid-run, so the channel waits for the
current batch to finish before acting.

### daemon restart failure (§8.5)

OTP received but daemon restart fails → **stay in `waiting_otp`** and rewrite
the card to "daemon 重启连续失败 N 次，请人工介入". There is **no** "3 failures
→ failed" path. Exiting `waiting_otp` only happens via a successful restart or
a "结束" command.

### Terminal states (§8.1)

| 终态 | 触发 |
|---|---|
| `completed` | `pending_count == 0` |
| `stopped` | 用户 "结束" / "终止" |
| `failed` | only startup-time validation/config errors |

---

## 6. Linear vs Kanban loop (§14.3)

### Linear mode (`kanban.enabled: false`)

ut-supervisor **directly drives Stage 2–5** through the v5 Worker SKILLs
(batch-selector → unit-test-executor → failure-handler → manifest-updater),
using `get_execute_config(state_path)` to feed `execute_batch`. The 3 Kanban
Gateways are not started and play no part. Bastion-loss handling and command
checking run as described in §4–§5.

### Kanban mode (`kanban.enabled: true`)

ut-supervisor **never touches the manifest** — Workers and the orchestrator
own it (the `ut-orchestrator` Worker subprocess runs Stage 5 then Stage 2 via
`orchestrator_round`, so the manifest has a single writer per round). The
supervisor only:

1. Preflight: `check_gateways_alive()` — all 3 Gateways must be active, else
   red card → exit.
2. Create the first `ut-orchestrator` Kanban task.
3. Each round: `check_gateways_alive()` (any down → `gateway_down` card, wait
   for systemd auto-recovery, poll), poll Kanban stats, run the shared
   command + Bastion checks, post a progress card read **read-only** from the
   manifest. `pending == 0 and running == 0` → `completed`.

In both modes the loop body, terminal check, command drain, and checkpoint
cadence are guaranteed by `workflow_loop_core`.

---

## 7. OTP progressive resend (§7 / §8.5)

When `waiting_otp`, resend the OTP request card on a backoff schedule. The
exact delays and @-user decisions come from the bastion module — do not
hardcode them:

```
attempt 1  → otp_resend_delay(1)  (5 min)
attempt 2  → otp_resend_delay(2)  (15 min)
attempt 3+ → otp_resend_delay(n)  (30 min, 60 min 封顶);  @user if otp_should_at_user(n)
```

Spec §7 reference cadence: attempt 1 → 5min, 2 → 15min, 3 → 30min(@user), 4+ → 60min(@user, 封顶).
There is **no timeout → failed** path; `waiting_otp` is left only by a valid
OTP (→ `running`) or "结束" (→ `stopped`).

---

## 8. Resume mapping (§9)

`init_or_resume(workflow_yaml, resume_from=<run_dir>)` reloads state; this
channel then maps the prior state:

| 旧状态 | 续跑行为 |
|---|---|
| `running` | → running，从 current_stage 继续（假设进程崩溃恢复） |
| `paused` | `apply_pending_config(state_path)`（如有）→ running |
| `waiting_otp` | 重走 OTP 流程（渐进重发从 attempt 1 开始） |
| `stopped` | **拒绝续跑**：飞书"该 run 已被停止，请新建运行" |
| `completed` | **拒绝续跑**：飞书"该 run 已完成，请新建运行" |
| `failed` | 重走启动校验（daemon/配置）→ 重置 running |

---

## 9. pending_config apply / discard (§10)

User "改参数 key=value" → `parse_command` extracts **whitelisted** keys only
(`batch_size`, `pytest_args`, `max_retry_per_test`, `timeout`); other keys are
silently ignored with a Feishu hint. The values are stashed under
`state["pending_config"]` in `workflow_state.json`.

| 规则 | 说明 |
|---|---|
| 只存白名单 key | 其他 key 忽略 |
| 空对象 `{}` | 只暂停、未改参数 |
| 不写回 workflow.yaml | 临时修改只对本次有效 |
| "继续" 时应用 | `apply_pending_config(state_path)` 合并到 config → 清空 pending_config |
| "结束" 时丢弃 | 不应用，直接清空 |
| paused 卡片展示 | 列出 pending_config 内容供用户确认 |

`apply_pending_config` merges `pending_config` into `config`, clears it, bumps
`last_update`, and returns the effective config. It is a no-op when empty.

---

## 10. Completion (§15)

No auto-archive. On completion: write final `manifest.json` +
`workflow_state.json` (status=completed), post a green completion card
(attach `git log master..2.5.1_ut_verify --oneline` auto-fix summary), mark
`current_run.json` completed. `bastion.stop_heartbeat()` on the way out;
Gateways and batch dirs are left untouched.

---

## Reference

`docs/superpowers/specs/2026-06-18-hermes-workflow-dual-channel-design.md`
(§14 process model & startup & main loop, §8 state machine & command matrix,
§9 resume mapping, §10 pending_config, §7 / §8.5 OTP progressive resend).
