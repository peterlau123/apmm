---
name: terminal-workflow
description: "UT Workflow linear-mode supervisor for vLLM unit tests. One-way Feishu progress, manual Bastion handling, no state machine. Use in interactive Claude sessions for local/terminal debugging."
version: 5.1.0
when_to_use: "User asks to run / resume / supervise the UT workflow interactively in this Claude session."
---

# terminal-workflow (v5 — linear supervisor channel)

## Data Flow

**test_load = working dataset, manifest = master record.**
test_load_xxx.json is read/written during the loop. manifest.json is only updated post-loop when pending==0.

### Pipeline

```
Init: collect (manifest from test_list or manifest_source)
  ↓
Stage 1: generate test_load (extract N tests from manifest via generate_test_load.py)
  ↓
[Loop] Stage 2: select_batch → Stage 3: execute (remote pytest)
       → Stage 4: handle_failures → Stage 4.5: update_test_load
       Loop until test_load pending == 0
  ↓
Stage 5: sync test_load → manifest (update_manifest_from_test_load.py)
```

### Retry / Resume

- Input: `workflow_state.json` + `test_load_xxx.json` (NOT manifest.json)
- Phase 2 retry → see `two-phase-handler` SKILL

## Startup Flow — 5-Step Script-Driven Sequence

> Each step runs a dedicated script. Do NOT improvise, merge, or skip.

### Step 1: Create Run Dir

```bash
python skills/ut/terminal-workflow/scripts/create_run_dir.py \
    --workflow-yaml <source_workflow_yaml> --mode terminal
```

Creates `runs/ut-{timestamp}/`, copies workflow.yaml, creates subdirs, updates `.agents/current_run.json`. Prints YAML param block.

> For resume (`resume_from` set): skip this step, use existing run_dir.

### Step 2: Parameter Confirmation

Read `run_dir/workflow.yaml` and present to user:

| Parameter | yaml key | Description |
|-----------|----------|-------------|
| test_list path | `input_filter.test_list_path` | test_list.txt path |
| manifest source | `input_filter.manifest_source` | existing manifest.json |
| strategy | `workflow.execution_strategy` | single-phase / two-phase |
| test_load count | `workflow.test_load.count` | tests to extract |
| batch_size | `config.batch_size` | tests per batch |
| max_retry | `config.max_retry_per_test` | max retries per test |
| resume | `config.resume_from` | empty=new, path=resume |

1. Render table to user
2. Wait: "confirm" or "key=value" to modify
3. Apply changes to `run_dir/workflow.yaml`

### Step 3: Prepare Data Files

```bash
python skills/ut/terminal-workflow/scripts/prepare_run_data.py \
    --run-dir <run_dir> --mode terminal \
    [--test-list <override>] [--manifest-source <override>] [--test-load-count <N>]
```

Copies manifest_source → manifest.json (or generates from test_list.txt), creates workflow_state.json, calls generate_test_load.py internally. Prints summary.

> For resume: skip this step (data files exist).

### Step 4: Bastion Check

```bash
python tools/agent.py --profile t_h20 ping
python tools/agent.py --profile t_h20 run "hostname"  # optional verify
```

On fail: ask user to re-authenticate bastion daemon. Do NOT enter loop if unreachable.

> Check once per session; skip if already verified.

### Step 5: Final Confirmation + Strategy Branch

```
=== Run Summary ===
  run_dir: <run_dir>
  manifest: <manifest_path> (N tests)
  test_load: <test_load_path> (M tests)
  strategy: <strategy>
  batch_size: <batch_size>
  bastion: connected/unreachable
Start? (y/N):
```

- **single-phase**: `loop_core.run()` with 4 Worker SKILLs (Stage 2-5 loop)
- **two-phase**: `auto_run_batches_two_phase.py` (Phase 1) → `two-phase-handler` (Phase 2)

## Channel Guarantees

- **One-way Feishu**: progress/completion/alert cards only
- **No auto Bastion recovery**: poll ping until user re-authenticates
- **No state machine**: `current_stage` is a breadcrumb, not a guard
- **No user-command channel**: `check_user_commands()` returns `[]`

## Channel Callbacks (→ `loop_core.run`)

| Callback | Behavior |
|----------|----------|
| `handle_checkpoint` | Feishu progress card → bump iteration/last_update on state_path |
| `handle_bastion_disconnect(reason)` | Log → Feishu alert → poll `ensure_connected()` → return on reconnect |
| `check_user_commands()` | Returns `[]` (Ctrl-C is pause/stop via KeyboardInterrupt) |
| `check_terminal_conditions` | `pending==0 && running==0 → (True, ..., "completed")` |

## Hard Constraints

1. **逐 stage 执行** — 检查 STAGE COMPLETED 输出 + workflow_state.json 状态后，才能执行下一步
2. **自检补救** — 每个 stage 后检查 workflow_state.json 是否更新，未更新则手动补救
3. **用户中断** — 每 10 batch 暂停输出检查报告

## What this SKILL does NOT do

- Does not start Bastion daemon (only `ensure_connected`)
- Does not call stage functions directly (Worker SKILLs own per-stage logic)
- Does not write to Kanban (hermes-workflow's responsibility)
- Does not consume Feishu webhooks / OTP callbacks

## When to switch to hermes-workflow

- Unattended / overnight runs
- Kanban progress board
- OTP-driven Bastion auto-recovery

## Related

- [two-phase-handler](../shared/two-phase-handler/SKILL.md) — Phase 2 retry
- [hermes-workflow](../hermes-workflow/SKILL.md) — Production auto channel
- Scripts in `scripts/` (13 files): `create_run_dir.py`, `prepare_run_data.py`, `loop_executor.py`, etc.
