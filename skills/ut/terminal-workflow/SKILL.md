---
name: terminal-workflow
description: UT Workflow - OpenCode/Claude Code linear-mode supervisor for vLLM unit tests. One-way Feishu progress, manual Bastion handling, no state machine.
version: 5.0.0
when_to_use: User asks to run / resume / supervise the UT workflow interactively in this Claude session.
---

# UT Workflow Skill (v5 — linear supervisor channel)

## Data Flow: test_load = working dataset, manifest = master record

test_load_xxx.json is the **working dataset** for the current run. All stages
(2-4.5) read and write test_load during the loop. manifest.json is the **master
record**, updated only once when test_load is fully processed (pending == 0).

This avoids polluting manifest.json with intermediate failure states and
keeps statistics stable until the run completes.

### Pipeline overview

```
Init: collect (manifest from test_list or manifest_source)
  |
  v
Stage 1: generate test_load (extract N tests from manifest)
  |
  v
[Loop] Stage 2: select_batch -> Stage 3: execute (remote pytest) 
       -> Stage 4: handle_failures -> Stage 4.5: update_test_load
       Loop Stage 2-4.5 until test_load pending == 0
  |
  v
Stage 5: sync test_load -> manifest (update_manifest_from_test_load.py)
```

### Stage 1: test_load generation

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

### Stage 2: batch selection (generate_batch.py)

Reads test_load, selects next batch of pending tests. Normal tests first,
distributed tests when no normal tests remain.

### Stage 3: batch execution (execute_batch.py)

Runs pytest remotely on GPU server. Normal batch: 1 GPU/test. Distributed
batch: torchrun with gpu_per_test GPUs/test.

### Stage 4: failure handling (failure-handler)

Reads batch_results.json, classifies failures, produces handled_tests.json
with retry/ignore/fix decisions.

### Stage 4.5: test_load update (update_test_load_two_phase.py)

Applies v5 merge to test_load: retry_count++, retriable_error->ignored,
handled overrides. Updates workflow_state.json batch status.

### Stage 5: post-loop manifest sync

When test_load pending == 0, sync results back to manifest.json:

```bash
python skills/ut/manifest-updater/scripts/update_manifest_from_test_load.py \
    --manifest-path <run_dir>/manifest.json \
    --test-load-path <run_dir>/test_load_xxx.json
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

## Startup Flow

> Each step uses explicit scripts. Do NOT improvise or skip steps.

### Step 1: Init (create run_dir + copy files)

For new run:
```bash
python skills/ut/terminal-workflow/scripts/init_workflow_state.py \
    --workflow-yaml <source_workflow_yaml>
```

This script automatically:
1. Creates `runs/ut-{timestamp}/` (run_dir)
2. Copies workflow.yaml to `run_dir/workflow.yaml` (original never modified)
3. Copies input files to run_dir (manifest_source -> copy manifest.json; test_list_path -> copy test_list.txt + generate manifest.json)
4. Creates `workflow_state.json` + `batches/` dir
5. Updates `.agents/current_run.json` pointer

Optional CLI overrides:
- `--test-list <path>`: override yaml's `input_filter.test_list_path`
- `--run-dir <path>`: specify run_dir explicitly

For resume (`resume_from` is set): skip this step, use existing run_dir.

### Step 2: Parameter Confirmation

Read config from `run_dir/workflow.yaml` (the copy, NOT the original), show to user:

| Parameter | yaml key | Default | Description |
|-----------|----------|---------|-------------|
| test_list path | input_filter.test_list_path | (from yaml) | test_list.txt (read-only reference) |
| manifest source | input_filter.manifest_source | null | manifest.json (read-only reference) |
| execution strategy | workflow.execution_strategy | two-phase | single-phase / two-phase |
| test_load count | workflow.test_load.count | 1000 | tests to extract from manifest |
| batch_size | config.batch_size | 8 | tests per batch |
| max_retry | config.max_retry_per_test | 3 | max retries per test |
| resume | config.resume_from | null | empty=new, path=resume |

**AI behavior:**
1. Read `run_dir/workflow.yaml`
2. Show parameter table to user
3. Wait for user confirmation ("confirm") or modification ("batch_size=16")
4. Apply modifications to `run_dir/workflow.yaml` (NOT the original)

> If user changes `test_list_path` or `manifest_source`, re-run Step 1 with the new source (`--test-list <new_path>`).

### Step 3: Generate test_load

For new run (skip if resuming and test_load already exists):
```bash
python tasks/ut/scripts/generate_test_load.py \
    --manifest-path <run_dir>/manifest.json \
    --count <confirmed_count> \
    --output-dir <run_dir> \
    --workflow-state <run_dir>/workflow_state.json
```
Creates `test_load_{count}_{timestamp}.json` and updates `workflow_state.json`
with the test_load path. All subsequent stages read from test_load.

### Step 4: Bastion Check

```bash
python -c "
from skills.ut.shared.ut_runner import _setup_bastion
from skills.ut.shared.config_loader import load_workflow_yaml, resolve_paths
config = load_workflow_yaml('<run_dir>/workflow.yaml')
paths = resolve_paths(config, '<run_dir>')
bastion = _setup_bastion('<run_dir>', config.get('bastion'), config.get('remote_server'), str(paths.get('feishu_config')), '<run_dir>/workflow_state.json')
print('Bastion OK' if bastion else 'Bastion FAILED')
"
```
If unreachable, surface failure to user and stop. Do NOT enter the loop.

### Step 5: Strategy Branch

Based on `execution_strategy` from `run_dir/workflow.yaml`:

- **single-phase**: Enter `loop_core.run()` with the 4 Worker SKILLs:
  - Stage 2: `generate_batch.py` reads test_load, selects batch
  - Stage 3: `execute_batch.py` runs remote pytest
  - Stage 4: failure-handler produces `handled_tests.json`
  - Stage 4.5: `update_test_load.py` applies v5 merge to test_load
  - Repeat until test_load pending == 0

- **two-phase**:
```bash
python tasks/ut/scripts/auto_run_batches_two_phase.py \
    --workflow-yaml <run_dir>/workflow.yaml \
    --run-dir <run_dir>
```
Phase 1 completes, then invoke two-phase-handler SKILL for Phase 2
(statistical analysis + human decision + retry).

## Trigger flow (this channel)

```mermaid
sequenceDiagram
    actor U as User
    participant CC as Agent Session
    participant B as Bastion(t_h20)
    participant L as loop_core
    U->>CC: "Run UT workflow"
    CC->>CC: Step 1: init_workflow_state.py (creates run_dir + copies yaml)
    CC->>U: Step 2: Show params from run_dir/workflow.yaml
    U->>CC: Confirm or modify
    CC->>CC: Apply mods to run_dir/workflow.yaml
    CC->>CC: Step 3: generate_test_load.py
    CC->>B: Step 4: _setup_bastion -> ensure_connected
    alt unreachable
        B-->>CC: fail
        CC->>U: Report and stop (do NOT enter loop)
    else reachable
        CC->>L: Step 5: loop_core.run() or auto_run_batches_two_phase.py
        L-->>CC: Feishu progress cards (optional)
        Note over CC,U: Pause/stop = user Ctrl-C
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
  Pause/stop is the user pressing Ctrl-C in this session.

---



### Step 6: Post-loop (sync test_load to manifest)

When test_load pending == 0:
```bash
python skills/ut/manifest-updater/scripts/update_manifest_from_test_load.py \
    --manifest-path <run_dir>/manifest.json \
    --test-load-path <run_dir>/test_load_xxx.json
```
Syncs test_load results back to manifest.json (master record).

## Channel callbacks (passed to `loop_core.run`)

### `handle_checkpoint(state, test_load)`
Send a Feishu progress card via `ut_runner.send_feishu_card(
feishu, "progress", test_load, iteration, batch_id=batch_id, mode="linear")`.
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

### `check_terminal_conditions(state, test_load)`
Delegate to `ut_runner.check_stop_conditions(state_path)`:
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
profiles documented in `tasks/ut/docs/guides/ut-runner.md`, with
systemd deployment covered by `tasks/ut/docs/guides/hermes-supervisor-service.md`
(ut-supervisor agent) and `tasks/ut/docs/guides/hermes-gateway-service.md`
(3 gateway instances).

---

## Workflow-level Retry（整批重跑）

当workflow停止后（完成/人工停止/错误超阈值），重新执行failed/error batches：

**输入文件：**
- `workflow_state.json` — batch执行状态
- test_load_xxx.json - 测试清单（工作数据集，非manifest.json）

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
