---
name: terminal-workflow
description: UT Workflow - OpenCode/Claude Code linear-mode supervisor for vLLM unit tests. One-way Feishu progress, manual Bastion handling, no state machine.
version: 5.0.0
when_to_use: User asks to run / resume / supervise the UT workflow interactively in this Claude session.
---

# UT Workflow Skill (v5 — linear supervisor channel)

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

- **Per-batch**: update_batch_state.py updates test_load (v5 merge: retry_count,
  retriable_error->ignored, handled_tests overrides) + workflow_state.json
  (batch status -> completed).
- **Post-loop**: update_manifest_from_test_load.py syncs test_load -> manifest.json
  (requires pending == 0 in test_load).

### Retry / Resume

- Input: workflow_state.json + test_load_xxx.json (NOT manifest.json)
- Phase 2 operates within test_load scope

## Startup Flow

### Step 1: Parameter Confirmation

When user triggers workflow (e.g. "开始运行单元测试" / "跑 ut workflow"):

**AI behavior:**
1. Determine environment (test l1-l4 / production) from user's message
2. Load corresponding workflow.yaml template
3. Show current config, ask user to confirm or modify:

| Parameter | yaml key | Default | Description |
|-----------|----------|---------|-------------|
| manifest 位置 | input_filter.test_list_path | (from yaml) | test_list.txt 原始路径 |
| 执行策略 | workflow.execution_strategy | two-phase | single-phase 或 two-phase |
| test_load 数量 | workflow.test_load.count | 1000 | 从 manifest 抽取的 test 数 |
| batch_size | config.batch_size | 8 | 每批测试数量 |
| max_retry | config.max_retry_per_test | 3 | 单测试最大重试次数 |
| resume | config.resume_from | null | 留空=新建, 填路径=续跑 |

4. User confirms ("确认") or modifies ("改 batch_size=16")
5. Apply modifications to the run's workflow.yaml copy

## Trigger flow (this channel)

```mermaid
sequenceDiagram
    actor U as 用户
    participant CC as Claude/OpenCode 会话
    participant R as hermes_runner
    participant B as Bastion(t_h20)
    participant L as loop_core
    U->>CC: 要求"跑/续 UT workflow"
    CC->>CC: 加载 ut/terminal-workflow + loop_core + 4 Worker SKILL
    CC->>R: validate_required_config(runs/ut-{timestamp}/workflow.yaml)
    CC->>R: init_or_resume(yaml, resume_from)
    R-->>CC: (run_dir, state_path, state, iteration)
    CC->>B: _setup_bastion → ensure_connected (单次探测)
    alt 不可达
        B-->>CC: 失败
        CC->>U: 报错并停止（不进循环）
    else 可达
        CC->>L: loop_core.run(回调...)
        L-->>CC: 单向飞书进度卡（可选）
        Note over CC,U: 暂停/停止 = 用户按 Ctrl-C
    end
```

---

## Channel guarantees (v5 simplifications)

- **One-way Feishu.** Progress / completion / alert cards only. No
  subscribe, no callback server, no remote command intake.
- **No automatic Bastion recovery.** If the executor returns
  `next_action == "wait"`, this channel logs + alerts and polls
  `ssh ping` until the user re-authenticates manually.
- **No state machine.** `current_stage` is a breadcrumb in
  `workflow_state.json`, not a guard. The loop body owns ordering.
- **No user-command channel.** `check_user_commands()` returns `[]`.
  Pause/stop is the user pressing Ctrl-C in this Claude session.

---

## Startup (Steps 2-6, after parameter confirmation)

### Step 2: Init

For new run:
```bash
python skills/ut/terminal-workflow/scripts/init_workflow_state.py \
    --workflow-yaml runs/ut-{timestamp}/workflow.yaml \
    --test-list <confirmed_test_list_path>
```
Creates run_dir, manifest.json (from test_list), workflow_state.json.

For resume (resume_from is set): skip init, use existing run_dir.

### Step 3: Generate test_load

For new run (skip if resuming and test_load already exists):
```bash
python tasks/ut/scripts/generate_test_load.py \
    --manifest-path <run_dir>/manifest.json \
    --count <confirmed_count> \
    --output-dir <run_dir> \
    --workflow-state <run_dir>/workflow_state.json
```
Creates test_load_{count}_{timestamp}.json and updates workflow_state.json
with the test_load path. All subsequent stages read from test_load.

### Step 4: Bastion Check

hermes_runner._setup_bastion(...) performs ensure_connected.
If unreachable, surface failure to user and stop. Do NOT enter the loop.

### Step 5: Strategy Branch

Based on execution_strategy from confirmed config:

- **single-phase**: Enter loop_core.run() with the 4 Worker SKILLs:
  - Stage 2: generate_batch.py reads test_load, selects batch
  - Stage 3: execute_batch.py runs remote pytest
  - Stage 4: failure-handler produces handled_tests.json
  - Stage 4.5: update_batch_state.py applies v5 merge to test_load
  - Repeat until test_load pending == 0

- **two-phase**: Call auto_run_batches_two_phase.py:
```bash
python tasks/ut/scripts/auto_run_batches_two_phase.py \
    --workflow-yaml runs/ut-{timestamp}/workflow.yaml \
    --run-dir <run_dir>
```
Phase 1 completes, then invoke two-phase-handler SKILL for Phase 2
(statistical analysis + human decision + retry).

### Step 6: Post-loop (sync test_load to manifest)

When test_load pending == 0:
```bash
python skills/ut/manifest-updater/scripts/update_manifest_from_test_load.py \
    --manifest-path <run_dir>/manifest.json \
    --test-load-path <run_dir>/test_load_xxx.json
```
Syncs test_load results back to manifest.json (master record).

## Channel callbacks (passed to `loop_core.run`)

### `handle_checkpoint(state, manifest)`
Send a Feishu progress card via `hermes_runner.send_feishu_card(
feishu, "progress", manifest, iteration, batch_id=batch_id, mode="linear")`.
On high error rate, switch to event `"alert"`. Bump `iteration` and
`last_update` on `state_path` while you're here.

### `handle_bastion_disconnect(reason)`
1. Log `"[ut-workflow] bastion disconnect: {reason}"` to console.
2. Send Feishu `"alert"` card with the reason.
3. Poll `bastion.ensure_connected()` every `bastion.heartbeat_interval`
   seconds. **Do not auto-reconnect** — the user re-authenticates the
   daemon out-of-band.
4. When `ensure_connected()` returns `True`, return control to the loop
   (do NOT mutate `state.flags`).

### `check_user_commands()`
Returns `[]`. Linear OpenCode has no out-of-band command channel — the
user interacts via this Claude session, and Ctrl-C is the pause/stop
signal handled by `loop_core`'s `KeyboardInterrupt` path.

### `check_terminal_conditions(state, manifest)`
Delegate to `hermes_runner.check_stop_conditions(state_path)`:
- `pending == 0 and running == 0` → `(True, "pending_count == 0", "completed")`
- otherwise `(False, "", "")`

---

## Fallback: missing Worker SKILL

If `loop_core` reports that a Worker SKILL reference was missing and it
had to reload from disk, accept it silently and continue. No restart, no
state mutation. The user is told only if the reload itself fails.

---

## What this SKILL deliberately does NOT do

- Does not start the Bastion daemon (only `ensure_connected`).
- Does not call `stage_select_batch / stage_execute / stage_handle_failures
  / stage_update_status`. Those functions were deleted in Phase 8 — the
  Worker SKILLs (loaded above) own the per-stage logic, invoked by
  `loop_core`.
- Does not write to the Hermes Kanban board. Kanban is `hermes-workflow`'s
  responsibility.
- Does not consume Feishu webhooks / OTP callbacks.

---

## When to switch channels

If the user asks for any of the following, route them to
`hermes-workflow` instead:
- Unattended / overnight runs.
- Parallel executor / fixer workers.
- Kanban progress board.
- OTP-driven Bastion auto-recovery.

Those features live in Plan 2 and require the Hermes Agent + Gateway
profiles documented in `tasks/ut/docs/guides/hermes-runner.md`, with
systemd deployment covered by `tasks/ut/docs/guides/hermes-supervisor-service.md`
(ut-supervisor agent) and `tasks/ut/docs/guides/hermes-gateway-service.md`
(3 gateway instances).

---

## Workflow-level Retry（整批重跑）

当workflow停止后（完成/人工停止/错误超阈值），重新执行failed/error batches：

**输入文件：**
- `workflow_state.json` — batch执行状态
- 	est_load_xxx.json - 测试清单（工作数据集，非manifest.json）

**调用SKILL：** `two-phase-handler`
- **Phase 2 Stage 1**: 统计分析失败batch
- **Phase 2 Stage 2**: 执行重试（需人工决策）

**触发条件：**
- Workflow状态为 `stopped` 或 `completed` 且有failed/error tests
- 用户请求"重跑失败的batch"

**相关文档：** `skills/ut/shared/two-phase-handler/SKILL.md`

---

## 硬性约束（不可违反）

### ⚠️ Agent 必须逐 stage 执行

**terminal-workflow Agent 必须逐 stage 执行，不得编写批量自动化脚本！**

正确流程：
1. 执行一个 stage（如 generate_batch）
2. 检查 STAGE COMPLETED 输出
3. 检查 workflow_state.json 状态
4. 输出状态报告给用户
5. 根据状态决策下一步

错误流程：
❌ 编写 Python 脚本批量执行多个 stage
❌ 使用循环自动化整个 workflow
❌ 跳过状态检查步骤

### ⚠️ 自检补救机制

**terminal-workflow 在每个 stage 后应自检 workflow_state.json 是否更新！**

如果发现未更新，应：
1. 输出警告：[WARN] Workflow State NOT UPDATED
2. 手动调用 update_workflow_state() 补救
3. 输出补救后的状态

**建议使用 loop_executor.py 工具**，它已内置自检补救逻辑。

### ⚠️ 用户中断检查点

**Agent 每执行 10 个 batch 后，必须暂停并输出检查报告！**

用户可随时输入 "pause" 或 "stop" 中断执行。

---

*版本: 5.1.0*
