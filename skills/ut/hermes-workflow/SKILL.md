---

name: hermes-workflow

description: Hermes-channel supervisor for the UT workflow. A long-running ut-supervisor Hermes Agent subscribes to Feishu, owns the full workflow state machine (running/paused/waiting_otp/completed/stopped/failed), auto-manages the Bastion daemon with OTP recovery, and drives the shared loop via workflow-loop-core.

version: 5.0.0

when_to_use: Loaded into the ut-supervisor profile when a Feishu trigger message ("跑 ut workflow" / "启动测试" / "开始 UT") matches, or via `hermes skill run hermes-workflow`. Production unattended channel — for OpenCode/Claude terminal debugging use ut/workflow instead.

---



# hermes-workflow (v5)



> ⚠️ **HARD CONTRACT — read first, before anything else in this file.**

>

> This 5-rule block is the **only** part of the SKILL the runtime treats as

> non-negotiable. If a rule below conflicts with anything later in this file,

> the rule wins.

>

> 1. **Output schemas are canonical for every Stage.** Stage 3 produces

>    `batch_results.json` via `execute_batch.py` (schema:

>    `skills/ut/unit-test-executor/batch_results_schema.json`). Stage 4

>    produces `handled_tests.json` via `generate_handled_manifest.py`.

>    Stage 5 mutates `test_load` via `update_test_load.py`. Each stage

>    REJECTS hand-rolled payloads through strict jsonschema validation +

>    (Stage 5 only) remote `stat` audit.

> 2. **State machine values are fixed.** `workflow.status ∈ {running,

>    paused, waiting_otp, completed, stopped, failed}`. Do NOT invent new

>    states ("done", "succeeded", "killed", ...). Transitions are the only

>    way to mutate status — direct writes to `workflow_state.json` are

>    forbidden.

> 3. **Bastion is single-tenant.** Only `BastionManager` owns the daemon

>    lifecycle. On `ConnectionError`, the active stage MUST return

>    `{"next_action": "wait", "reason": ...}` and let the supervisor's

>    reconnect loop handle it. Do NOT spawn ad-hoc `agent.py login` or

>    daemon restarts from inside a stage.

> 4. **Stages run via the canonical scripts, period.** No inline pytest

>    invocation, no hand-rolled remote ssh, no LLM-fabricated stage output.

>    If a script fails, fail loud (write the error into the run log) — do

>    NOT synthesize a plausible Stage output to keep the loop moving.

> 5. **All durable timestamps are UTC ISO 8601 with Z suffix.** Pattern:

>    `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$`. Local times

>    leak into runs/ paths and break catch-up logic — use

>    `datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")`.



## Data Flow: test_load = working dataset, manifest = master record



test_load_xxx.json is the **working dataset** for the current run. All stages

(2-5) read and write test_load during the loop. manifest.json is the **master

record**, updated only once when test_load is fully processed (pending == 0).



This avoids polluting manifest.json with intermediate failure states and

keeps statistics stable until the run completes.



### Stage 1: test_load generation



When workflow starts (after Stage 0 environment selection):



1. Call generate_test_load.py to extract a subset from manifest

2. Generates test_load_{count}_{timestamp}.json

3. Updates workflow_state.json with the test_load path

4. All subsequent stages operate on test_load



```bash

python tasks/ut/scripts/generate_test_load.py \

    --manifest-path runs/ut-{timestamp}/manifest.json \

    --count 1000 \

    --output-dir runs/ut-{timestamp} \

    --workflow-state runs/ut-{timestamp}/workflow_state.json

```



### State updates during the loop



- **Per-batch**: update_test_load_two_phase.py updates test_load (v5 merge: retry_count,

  retriable_error->ignored, handled_tests overrides) + workflow_state.json

  (batch status -> completed).

- **Post-loop**: update_manifest_from_test_load.py syncs test_load -> manifest.json

  (requires pending == 0 in test_load).



### Retry / Resume



- Input: workflow_state.json + test_load_xxx.json (NOT manifest.json)

- Phase 2 operates within test_load scope



## Stage 0: Parameter Confirmation via Feishu



When user sends a trigger message ("跑L4" / "跑 ut workflow" / "正式生产"):



**AI behavior:**

1. Classify intent (ut_runner Layer 1 regex -> Layer 2 LLM)

2. Determine environment from intent (tier l1-l4 / production)

3. Load corresponding workflow.yaml template

4. Send Feishu parameter confirmation card (editable):



| Parameter | yaml key | Default | Description |

|-----------|----------|---------|-------------|

| test_list 路径 | input_filter.test_list_path | (from yaml) | test_list.txt 路径（与 manifest_source 二选一） |

| manifest 来源 | input_filter.manifest_source | null | 已有 manifest.json 路径（优先于 test_list_path） |

| 执行策略 | workflow.execution_strategy | two-phase | single-phase 或 two-phase |

| test_load 数量 | workflow.test_load.count | 1000 | 从 manifest 抽取的 test 数 |

| batch_size | config.batch_size | 8 | 每批测试数量 |

| max_retry | config.max_retry_per_test | 3 | 单测试最大重试次数 |

| resume | config.resume_from | null | 留空=新建, 填路径=续跑 |



5. User replies "确认" or "改 KEY=VALUE" (10s timeout for tier, 5min for legacy)

6. Apply modifications to run's workflow.yaml copy



## Trigger flow + environment topology



```mermaid

sequenceDiagram

    actor U as 用户

    participant F as 飞书 bot(cli_aaad…, DM oc_ed80…)

    participant S as ut-supervisor (gateway)

    participant R as ut_runner

    participant B as Bastion(t_h20)

    participant L as loop_core

    U->>F: "跑 ut workflow"

    F->>S: 关键词匹配触发

    S->>S: 加载 hermes-workflow + loop_core + 4 Worker SKILL

    S->>F: 参数确认卡(蓝色, 5 字段)

    U->>F: "确认" / "yaml=…" / "改 KEY=VAL"

    F->>S: 命令

    S->>R: validate_required_config (+kanban: check_gateways_alive)

    S->>R: init_or_resume → (run_dir, state, …)

    S->>B: BastionManager.ensure_connected

    alt daemon 不可用

        S->>F: OTP 卡片(渐进重发 5→15→30→60min)

        U->>F: 6 位 OTP

        F->>S: otp

        S->>B: 同步重启 daemon → mark_connected → running

    end

    S->>B: start_heartbeat(on_disconnect)

    S->>L: loop_core.run(回调...)

    loop 每轮 Stage5 之后

        L->>S: handle_checkpoint

        S->>F: 进度卡 + check_user_commands

    end

```



```mermaid

flowchart LR

    U[用户]

    BOT[飞书 bot<br/>cli_aaad… / DM oc_ed80…]

    SUP[ut-supervisor gateway<br/>唯一飞书订阅者]

    GO[ut-orchestrator<br/>Stage5+Stage2]

    GE[ut-executor<br/>Stage3 远程 pytest]

    GF[ut-fixer<br/>Stage4 修复]

    BAS[Bastion daemon<br/>profile t_h20 / OTP]

    REMOTE[(远程 GPU<br/>Docker + pytest)]

    U <--> BOT

    BOT <--> SUP

    SUP --> GO --> GE --> GF

    GE -->|SSH 复用| BAS --> REMOTE

```



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



Difference from `ut/terminal-workflow` (terminal channel): that channel has no state

machine, no paused/waiting_otp, and Bastion is human-maintained.



---



## 2. Tooling — `ut_runner.py`



Import the runner as a tool module (it no longer inlines stage logic):



```python

from ut_runner import (

    parse_command,           # text → Command or None (Layer 1 regex)

    classify_intent_llm,     # text → Command (Layer 2 LLM, with llm_invoker)

    Command,                 # dataclass: intent / confidence / args / source / raw_text

    init_or_resume,          # (run_dir, state_path, state, iteration)

    validate_required_config,# (ok, missing_keys)

    check_gateways_alive,    # {profile: bool}  (kanban preflight + per-round)

    get_execute_config,      # flat config for execute_batch

    apply_pending_config,    # merge pending_config → config on resume

    refresh_test_load_stats,  # tally test_load statuses into state

    check_stop_conditions,   # (done, reason, status)

    # orchestrator_round moved to hermes-workflow/scripts/orchestrator_round.py

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



The supervisor distinguishes **two trigger paths** depending on what

`parse_command(text)` + `classify_intent_llm(text)` (`ut_runner` Layer 1 +

Layer 2) classify the trigger message as. See the spec §4 for the two-layer

intent recognizer.



```

1. 用户飞书发任意消息 → ut-supervisor Agent 收到

2. 意图识别（ut_runner Layer 1 → Layer 2）

     a) Layer 1: parse_command(text) → otp/stop/pause/resume/change_config

        命中 → 直接派发到状态机（§5 命令矩阵），不进启动流程

     b) Layer 1 miss → Layer 2: classify_intent_llm(text) → Command

        intent ∈ {start_l1..l4, start_production} → 进入【启动确认分支】(§3.A)

        intent == change_config → 派发到状态机

        intent == unknown → 飞书发帮助卡，列出合法触发词（结束）

        legacy 关键词 "跑 ut workflow" / "启动测试" / "开始 UT" 在 v5 走 Layer 2：

        - **无 tier 后缀**（裸短语）→ 预期分类为 `unknown` → §3.D 帮助卡

        - 带 tier 后缀（"跑 L4"）或 "正式 / 生产 / 全量" 字眼 → 按 §3.A 走

        （这是 v5 的保守门：避免误触发数小时生产 run；v4 直接进 §3.B 的旧行为已废弃）

3. 一次性加载：hermes-workflow + workflow-loop-core

              + 4 份 Worker SKILL（batch-selector / unit-test-executor /

                failure-handler / manifest-updater）

4. 按 §3.A（tier / production 一键触发）或 §3.B（自由参数确认卡）继续

```



### §3.A - Unified Startup Sequence



After parameter confirmation (Stage 0):



```

A1. validate_required_config(load_yaml(yaml_path))

      - test_list_path or manifest_source at least one

      - config.remote_server exists

      - kanban.enabled=true: check_gateways_alive() all active

      - Any failure -> red error card -> exit



A2. init_or_resume(yaml_path, resume_from)

      -> (run_dir, state_path, state, iteration)

      -> Creates run_dir, manifest.json, workflow_state.json



A3. Generate test_load (skip if resuming and test_load exists):

      python generate_test_load.py \

          --manifest-path <run_dir>/manifest.json \

          --count <confirmed_count> \

          --output-dir <run_dir> \

          --workflow-state <run_dir>/workflow_state.json

      -> Creates test_load_xxx.json

      -> Updates workflow_state.json with test_load path



A4. Bastion bring-up + start_heartbeat

      daemon unavailable -> waiting_otp (§7 progressive OTP resend)



A5. Strategy branch (based on execution_strategy):

      single-phase -> loop_core.run() (Stage 2-5 loop)

      two-phase    -> auto_run_batches_two_phase.py (Phase 1 batch loop)

                   -> two-phase-handler SKILL (Phase 2 retry)



A6. Post-loop (when test_load pending == 0):

      python update_manifest_from_test_load.py \

          --manifest-path <run_dir>/manifest.json \

          --test-load-path <run_dir>/test_load_xxx.json

      -> Syncs test_load -> manifest.json (master record)

```



**Startup state machine interlock:**



| Current supervisor state | start_* intent | Action |

|---|---|---|

| idle | any | Proceed to A1 |

| running / paused / waiting_otp | any | Red card: "already running (status=X), stop or pause first" |



### §3.C — Tier → yaml 固化映射表



```yaml

# 来源：tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §2.2

start_l1:

  yaml: tests/ut/integration/fixtures/workflow.l1.yaml

  test_list: tests/ut/integration/fixtures/l1_smoke_list.txt

  mode: linear           # kanban.enabled=false

  eta: "< 1 min"

start_l2:

  yaml: tests/ut/integration/fixtures/workflow.l2.yaml

  test_list: tests/ut/integration/fixtures/mini_test_list.txt

  mode: linear

  eta: "~ 3 min"

start_l3:

  yaml: tests/ut/integration/fixtures/workflow.l3.yaml

  test_list: tests/ut/integration/fixtures/l3_fast_subset.txt

  mode: linear

  eta: "~ 15 min"

start_l4:

  yaml: tests/ut/integration/fixtures/workflow.l4.yaml

  test_list: tests/ut/integration/fixtures/l4_test_list_v2.txt

  mode: kanban

  eta: "~ 60 min"

start_production:

  yaml: tasks/ut/deployment/production/config/workflow.yaml

  test_list: (由 yaml 自定义)

  mode: kanban           # 生产默认 kanban

  eta: "hours – days"

```



`mode` / `eta` 仅用于卡片展示；真正生效的是 yaml 内的 `kanban.enabled`。



### §3.D — 帮助卡（intent=unknown 时回显）



`classify_intent_llm` 返回 `intent=unknown`（含裸 "跑 ut workflow" 这种保守门

拦截）时，supervisor 发一张帮助卡列合法触发词，结束本轮（不进任何状态机）。



```markdown

🤔 没看懂你想触发哪个 run。合法触发词：



▸ tier 测试（蓝色卡）：

    "跑 L1" / "跑 L2" / "跑 L3" / "跑 L4"

    "L4 走起" / "跑 ut workflow 的 l4 测试"



▸ 正式生产（橙色 + 警告卡）：

    "正式开跑" / "跑全量" / "跑正式生产"



▸ 改配置：

    "改 batch_size 为 10" / "把 max_retry 改成 5"



▸ 控制命令：

    "暂停" / "继续" / "停止"



裸 "跑 ut workflow" 不再自动派发（避免误触发生产）—— 请补 tier 后缀

或写明 "正式 / 生产 / 全量"。

```



卡片模板 `template=grey`，不要求回复；用户重新发合法短语即重新进 Layer 2。



Required-config validation maps directly to `validate_required_config`

(input_filter + remote_server) plus, in Kanban mode, a `check_gateways_alive`

gate that all 3 Gateways report `True`.



---



## 4. Channel callbacks (wired into `loop_core.run`)



`workflow-loop-core` exposes `loop_core.run(stage_skills, handle_checkpoint,

handle_bastion_disconnect, check_user_commands, check_terminal_conditions)`.

This channel supplies:



### `handle_checkpoint(state, test_load)`



Called after every successful Stage 5 (and each Kanban poll round):



1. `refresh_test_load_stats(state_path, test_load_path)` → tally into state.

2. Post a progress card via `send_feishu_card(feishu, "progress", test_load, iteration, ...)`.

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



Reads the Feishu group and runs the two-layer intent recognizer on every

new message:



1. **Layer 1** (regex): `parse_command(text)` → returns a `Command` if the

   message matches one of 6 anchored regex patterns (`otp`/`otp_with_id`/

   `stop`/`pause`/`resume`/`change_config`). If matched, dispatch directly

   to the state machine matrix (§8.2).

2. **Layer 2** (Agent's own LLM): if Layer 1 returns `None`, the ut-supervisor

   Agent itself reads SOUL.md §Intent classification and produces a JSON

   string per that schema. Pass it to `classify_intent_llm(text, llm_output)`

   which parses & validates the JSON into a `Command` with `source="llm"`

   and `intent` ∈ `{start_l1..l4, start_production, change_config, unknown}`.

   - `start_*` / `change_config`: queue for the startup-sequence hook

     (§3 step 2 — only processed in idle state).

   - `unknown`: the supervisor may post a brief "help" card listing

     trigger words.



There is **no external LLM invoker** — the Agent's reasoning IS the LLM.

`classify_intent_llm` is purely a parser/validator over the JSON the Agent

already produced.



(Linear `ut/terminal-workflow` returns `[]` here; this channel actually reads Feishu.)



### `check_terminal_conditions(state, test_load)`



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



ut-supervisor **never touches test_load** — Workers and the orchestrator

own it (the `ut-orchestrator` Worker subprocess runs Stage 5 then Stage 2 via

`orchestrator_round`, so test_load has a single writer per round). The

supervisor only:



1. Preflight: `check_gateways_alive()` — all 3 Gateways must be active, else

   red card → exit.

2. Create the first `ut-orchestrator` Kanban task.

3. Each round: `check_gateways_alive()` (any down → `gateway_down` card, wait

   for systemd auto-recovery, poll), poll Kanban stats, run the shared

   command + Bastion checks, post a progress card read **read-only** from

   test_load. `pending == 0 and running == 0` → `completed`.



In both modes the loop body, terminal check, command drain, and checkpoint

cadence are guaranteed by `workflow-loop-core`.



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



### §10.1 — Tier completion (L1/L2/L3/L4)



When the run was triggered via a tier intent (`start_l1..l4` from §3.A):



1. **Run `check_expected.py`**:

   ```

   python tasks/ut/scripts/check_expected.py \

       --run-dir <run_dir> \

       --expected <tier_expected_json> \

       --output-card-json <run_dir>/check_result.json

   ```

   - `<tier_expected_json>` comes from the tier map (§3.C):

     `tests/ut/integration/fixtures/L{1,2,3,4}_expected.json`

   - exit code 0 → PASS, 1 → FAIL (headline verdict).

   - exit code 2 → expected file parse error → treat as ERROR in the card.



2. **Read the verdict** from `<run_dir>/check_result.json`.



3. **Post tier completion card** via `feishu.send_tier_completion_card(verdict, tier, run_dir)`:

   - PASS → green card with emoji ✅, assertion summary

   - FAIL → red card with emoji ❌, failed hard assertions list (capped at 8)



4. **Write final manifest** + `workflow_state.json` (status=completed).

5. **Mark `current_run.json`** completed.

6. **`bastion.stop_heartbeat()`** on the way out.



### §10.2 — Production completion



When the run was triggered via `start_production` (or legacy keyword that

wasn't classified into a tier):



1. **No `check_expected.py`** — production has no expected-outcome fixture.

2. **Post plain completion card** via `send_feishu_card(feishu, "complete", test_load, iteration)`.

   (Green card with progress stats: passed/failed/error/pending counts.)

3. Attach `git log master..<branch> --oneline` auto-fix summary if applicable.

4. Write final manifest + `workflow_state.json`, mark `current_run.json`,

   `bastion.stop_heartbeat()` — same as tier completion.



### §10.3 — How the supervisor knows which path to take



The supervisor stores the trigger intent in `workflow_state.json` at startup

(key `trigger_intent`, value `start_l1|start_l2|start_l3|start_l4|start_production`).

On terminal state (`check_stop_conditions()` returns done=True), read

`state["trigger_intent"]`:

- starts with `start_l` and not `start_production` → §10.1

- `start_production` or absent → §10.2



No auto-archive. Gateways and batch dirs are left untouched.



---



## 11. Pitfalls (lessons from real incidents)



### 11.1 `tools/agent.py serve` must be started as a true background process



`agent.py serve t_h20 ...` is a long-lived daemon holding the SSH session. If

you invoke it through Hermes's `terminal` tool in foreground mode, the default

180-second timeout will SIGKILL it mid-handshake, leaving a half-dead daemon

state: `ping` succeeds (socket bound) but `run` hangs / returns `Socket is

closed` (shell session never finished setup).



**Correct invocation**: `terminal(background=True, ...)` for `serve`. Pair with

`agent.py -p t_h20 stop` first if there's a stale daemon to clear. Verify with

two round-trip `run` calls separated by ≥90 seconds before considering the

daemon healthy.



This applies to BOTH the initial Bastion bring-up in `init_or_resume` AND the

OTP recovery path triggered by `bastion.on_disconnect`.



### 11.2 Trust-but-verify stage-3 results (anti-fabrication audit)



A misbehaving Stage-3 worker can fabricate `batch_results.json` without

actually executing `pytest`. The 2026-06-22 incident on run

`ut-20260621-234651` produced fabricated stats (`passed=1 / failed=1 /

ignored=1`), a fake NCCL error classified as `resource-insufficient` triggering

a spurious supervisor pause, and an out-of-band "UT Workflow完成报告" sent

directly from `D:/workspace/apmm/scripts/send_feishu_report.py` (worker-written,

using a Claude-side Feishu token) to the ai-engineer Feishu group.



**Supervisor responsibility after each stage-3 completion** (before handing

off to handle_failures / Stage 4):



1. **Validate `batch_results.json` shape**: for every test entry, verify that

   `status` matches `exit_code` + `duration_seconds`. Specifically:

   - `status: passed/failed` AND `duration_seconds: null` → ⚠ fabrication suspect

   - `log_path` present but path is relative or empty → ⚠ fabrication suspect

2. **Stat the remote `log_path`**: `agent.py -p t_h20 run --timeout 15 "ls -la <log_path>"`.

   If the file doesn't exist on the bastion target, the worker fabricated the

   results. Stop the loop, mark the run `invalidated` (do not `pause`), and

   surface a red error card naming the offending stage.

3. **Cross-check container state**: `ps -ef | grep pytest` inside the container

   the worker claimed to use, and `find /gpfs/.../ut_logs/ -mmin -60` for fresh

   log files. If both are empty but `batch_results.json` claims work happened,

   that's the fabrication signature.



If fabrication is confirmed: `mv test_load_xxx.json test_load_xxx.json.fabricated.bak`

and `mv <batch_dir> <batch_dir>.fabricated.bak`, write an `INVALID.md` with

evidence, and post a red Feishu card. Do **not** resume — test_load is

poisoned and Stage 2 (batch-selector) will see no pending tests left.



### 11.3 Workers must not send Feishu / Lark messages out-of-band



By design only the supervisor (this channel) talks to Feishu. The 2026-06-22

incident showed a worker can bypass this by writing a Python script that calls

`open.feishu.cn` directly with a Feishu token harvested from

`~/.claude/skills/feishu-webhook-skill/`. This is documented as forbidden in

the `unit-test-executor` and `failure-handler` SKILLs (§禁止操作 hard

contract). If the supervisor sees a delivery in the ai-engineer chat (or any

non-supervisor chat) referring to a UT run id, that's a worker exfiltration

event — log it and tighten the SKILLs further.



### 11.4 Stale monitor cron jobs outliving invalidated runs



When a run is invalidated, any cron monitor created for it (e.g.

`ut-resume-monitor-<run_id>`) will keep firing and posting misleading status.

On invalidation, also: `hermes -p <profile> cron remove <job_id>` for every

monitor cron created for that run_id.



---



## Workflow-level Retry（整批重跑）



当workflow停止后（完成/人工停止/错误超阈值），重新执行failed/error batches：



**输入文件：**

- `workflow_state.json` — batch执行状态

- test_load_xxx.json - 测试清单（工作数据集，非manifest.json）



**调用SKILL：** `two-phase-handler`

- **Phase 2 Stage 1**: 统计分析失败batch

- **Phase 2 Stage 2**: 执行重试（需人工决策）



**触发方式：**

- 飞书命令："重跑失败的batch" / "retry failed"

- Supervisor调用 `two-phase-handler` SKILL



**相关文档：** `skills/ut/shared/two-phase-handler/SKILL.md`



---



## 硬性约束（不可违反）



### ⚠️ Supervisor 必须逐 stage 调度



**hermes-workflow Supervisor 必须在每个 Worker 完成后检查状态，不得批量调度！**



正确流程：

1. 调度 batch-selector Worker

2. 检查 Worker 返回的 STAGE COMPLETED 输出

3. 检查 workflow_state.json 状态

4. 输出状态报告

5. 决定是否调度下一个 Worker



错误流程：

❌ 批量调度多个 Worker

❌ 使用循环自动化整个 workflow

❌ 跳过状态检查步骤



### ⚠️ Worker 必须更新状态



**每个 Worker 完成任务后，必须检查 workflow_state.json 是否正确更新！**



Supervisor 应验证：

- batch-selector：batches[batch_id].status == 'generated'

- unit-test-executor：batches[batch_id].status == 'completed'



如果未更新，Supervisor 应补救更新。



---



*版本: 5.1.0*

