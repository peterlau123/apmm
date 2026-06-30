# Hermes Kanban Integration

> **注意：** `.agents/workflow.yaml` 已废弃（2026-06-29），配置机制已迁移至 `tasks/ut/deployment/production/config/` 模板库 + `runs/ut-{timestamp}/` 副本机制。运行时配置副本路径：`runs/ut-{timestamp}/workflow.yaml`。

## Overview

Hermes Kanban is the outer orchestration layer for UT workflow. In Kanban mode, task state is stored in Hermes board `apmm-ut`, and the Hermes gateway embedded dispatcher dispatches ready tasks to worker profiles.

## Current Version

| Component | Version / Value |
|-----------|-----------------|
| Hermes Agent | v0.16.0 |
| Board | `apmm-ut` |
| Workflow config | `runs/ut-{timestamp}/workflow.yaml`（运行时副本） |
| Kanban enabled | `kanban.enabled: true` |
| Dispatcher | embedded in `hermes gateway start` |

## Profiles

| Profile | Responsibility |
|---------|----------------|
| `ut-orchestrator` | Create batch tasks and coordinate workflow progress |
| `ut-executor` | Execute pytest batches on `t_h20` |
| `ut-fixer` | Analyze failures and create fix / retry actions |

## Hermes v0.16 Commands

```bash
# Board
hermes kanban boards list
hermes kanban boards switch apmm-ut

# Tasks
hermes kanban list
hermes kanban show <task_id>
hermes kanban create "UT Workflow: Orchestrate run" --assignee ut-orchestrator --priority 1
hermes kanban unblock <task_id> --reason "..."
hermes kanban archive <task_id>

# Dispatcher
hermes kanban dispatch --dry-run --json
hermes kanban dispatch --max 3
hermes gateway run
hermes gateway status
hermes gateway list

# Diagnostics
hermes kanban stats
hermes kanban diagnostics
hermes kanban runs <task_id>
```

`hermes kanban tasks ...` is obsolete for the current Hermes v0.16 CLI.

## Start Kanban Daemon

Use the project wrapper:

```bash
python skills/ut/terminal-workflow/scripts/start_gateway.py --workflow-yaml runs/ut-{timestamp}/workflow.yaml
```

> **注：** 旧命令 `--workflow-yaml .agents/workflow.yaml` 已废弃，请使用当前运行副本路径。

The wrapper:

1. Checks `hermes version`
2. Switches to board `apmm-ut`
3. Starts background `hermes gateway run` processes for `ut-orchestrator`, `ut-executor`, and `ut-fixer`
4. Uses the gateway embedded Kanban dispatcher in Hermes v0.16

`hermes gateway start` may prompt to install a scheduled service, so the project wrapper uses foreground `hermes gateway run` in detached background mode. `hermes kanban daemon` is deprecated in Hermes v0.16 unless forced; do not run it together with gateway because both dispatchers can race for task claims.

## Remote Execution Rule

UT workers must use the project SSH daemon helper:

```bash
python tools/agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_compile <command>"
```

Workers must not call plain `ssh` to bastion. Historical blocked Kanban tasks failed because worker profiles attempted direct SSH key authentication to `10.10.192.55`, while the project requires `tools/agent.py` with an already-started OTP-backed daemon.

Workers must not directly stop or restart `agent.py` daemon. If the daemon is unavailable, use the Feishu approval gate:

```bash
python skills/ut/terminal-workflow/scripts/request_daemon_approval.py \
  --profile t_h20 \
  --task-id <kanban_task_id> \
  --reason "agent.py daemon unavailable during UT execution"
```

If `ping` succeeds but `run` commands timeout or the daemon appears stuck, force the approval gate:

```bash
python skills/ut/terminal-workflow/scripts/request_daemon_approval.py \
  --profile t_h20 \
  --task-id <kanban_task_id> \
  --reason "agent.py daemon stuck: ping OK but run timeout" \
  --force
```

The script sends a Feishu approval request and waits for a reply like `OTP 123456`. OTP is used only for the current daemon restart and must not be written to task comments, logs, summaries, or result files.

Before dispatching UT executor tasks, verify:

```bash
python tools/agent.py -p t_h20 ping
```

Expected:

```text
[OK] Daemon is running
```

## Task Creation

Create a root orchestration task:

```bash
hermes kanban create "UT Workflow: Orchestrate run" \
  --assignee ut-orchestrator \
  --priority 1 \
  --body "Use runs/ut-{timestamp}/workflow.yaml. Remote execution must use python tools/agent.py -p t_h20 run. Container: v0.13.0_torch2.5.1_compile. Do not use plain ssh."
```

Executor tasks created by the orchestrator should include:

- `batch_config.json` path
- remote profile: `t_h20`
- docker container: `v0.13.0_torch2.5.1_compile`
- pytest args from `runs/ut-{timestamp}/workflow.yaml`
- instruction to use `tools/agent.py`

## Recovery

If stale tasks block the board:

```bash
hermes kanban diagnostics
hermes kanban show <task_id>
hermes kanban archive <task_id>
```

If dispatcher is not running:

```bash
python skills/ut/terminal-workflow/scripts/start_gateway.py --workflow-yaml runs/ut-{timestamp}/workflow.yaml
```

> **注：** 旧命令路径 `.agents/workflow.yaml` 已废弃。

If remote execution fails with daemon errors:

```bash
python tools/agent.py -p t_h20 ping
```

If not running, use the approval gate:

```bash
python skills/ut/terminal-workflow/scripts/request_daemon_approval.py \
  --profile t_h20 \
  --task-id <kanban_task_id> \
  --reason "agent.py daemon unavailable"
```

Manual fallback:

```powershell
cd D:\workspace\apmm\tools
python agent.py serve t_h20
```

## File Paths

| Component | Path |
|-----------|------|
| Kanban DB | `C:\Users\admin\AppData\Local\hermes\kanban\boards\apmm-ut\kanban.db` |
| Orchestrator profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-orchestrator\` |
| Executor profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-executor\` |
| Fixer profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-fixer\` |
| workflow.yaml | `runs/ut-{timestamp}/workflow.yaml`（运行时副本） |

> **历史路径变更：** 原 `.agents/workflow.yaml` 已废弃（2026-06-29），配置模板位于 `tasks/ut/deployment/production/config/workflow.yaml`。
