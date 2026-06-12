# Hermes Kanban Integration

## Overview

Hermes Kanban integrates with UT Workflow as an **outer orchestration layer**, replacing the current single-session workflow loop with distributed task scheduling.

## Core Question: How Does Workflow Actually Run?

### Current Mode (workflow.yaml: kanban.enabled: false)

```
User runs: python -m skills.ut.workflow.main
    |
    v
Single Agent Session
    |
    v
Agent reads SKILL.md, follows workflow stages
    |
    v
Agent executes: collect → select → execute → handle → update
    |
    v
Agent loop continues until all batches done
```

**Characteristics:**
- One long-running Agent session
- Sequential batch execution
- SKILL.md defines the workflow
- No task persistence between runs

### Kanban Mode (workflow.yaml: kanban.enabled: true)

```
User runs: hermes kanban gateway start apmm-ut
    |
    v
Gateway Process (runs continuously)
    |
    +-- Dispatcher (60s tick)
    |       |
    |       v
    |   Query kanban.db for ready tasks
    |       |
    |       v
    |   Claim task via CAS (atomic lock)
    |       |
    |       v
    |   Spawn Hermes Agent subprocess
    |       |
    |       v
    |   Agent reads SOUL.md + task body
    |       |
    |       v
    |   Agent executes work autonomously
    |       |
    |       v
    |   Agent calls kanban_complete()
    |       |
    |       v
    |   Task status: done
    |
    +-- Repeat every 60s
```

**Characteristics:**
- Persistent Gateway process
- Parallel task execution (multiple workers)
- SOUL.md defines worker behavior
- Task state persisted in kanban.db
- Automatic retry on failure
- Dependency-based task scheduling

## Key Differences

| Aspect | Current Mode | Kanban Mode |
|--------|-------------|-------------|
| Orchestration | Single Agent session | Gateway dispatcher |
| Workflow definition | SKILL.md | SOUL.md per role |
| Task state | In-memory | SQLite (kanban.db) |
| Parallelism | Sequential batches | Multiple workers |
| Persistence | Lost on crash | Survives restart |
| Retry | Manual | Automatic |

## Task Lifecycle

```
Created (status: pending)
    |
    v
Dependencies satisfied? 
    |-- No: blocked (waiting for parent)
    |-- Yes: ready
            |
            v
        Gateway claims task
            |
            v
        status: in_progress
            |
            v
        Worker Agent executes SOUL.md
            |
            v
        Success? 
            |-- Yes: done
            |-- No: failed (retry after delay)
```

## Profile Roles

### ut-orchestrator
- **Responsibility:** Create batch tasks and assign to executors
- **SOUL.md:** Defines orchestrator behavior
- **Creates:** executor tasks with batch config

### ut-executor
- **Responsibility:** Execute unit test batches
- **SOUL.md:** Defines executor behavior
- **Creates:** fixer tasks for failed tests

### ut-fixer
- **Responsibility:** Fix failed tests and retry
- **SOUL.md:** Defines fixer behavior
- **Creates:** Nothing (leaf node)

## Setup Guide

### 1. Create Kanban Board

```bash
hermes kanban boards create apmm-ut --name "APMM UT Workflow"
```

### 2. Create Worker Profiles

```bash
# Create profiles (clone from ai-engineer)
for role in orchestrator executor fixer; do
  hermes profile create ut-$role --clone ai-engineer
done

# Write SOUL.md for each profile
# See: C:\Users\admin\AppData\Local\hermes\profiles\ut-*\SOUL.md
```

### 3. Enable in workflow.yaml

```yaml
kanban:
  enabled: true
  board: apmm-ut
  profiles:
    orchestrator: ut-orchestrator
    executor: ut-executor
    fixer: ut-fixer
```

### 4. Start Gateway

```bash
# Start 3 gateways (one per role)
hermes kanban gateway start apmm-ut --profile ut-orchestrator
hermes kanban gateway start apmm-ut --profile ut-executor
hermes kanban gateway start apmm-ut --profile ut-fixer
```

## Verification

### Test Dependency Chain

```bash
# Create orchestrator task
hermes kanban tasks create apmm-ut --title "Orchestrator: Analyze batch" --profile ut-orchestrator

# Create executor task (depends on orchestrator)
hermes kanban tasks create apmm-ut --title "Executor: Run batch-001" --profile ut-executor --depends-on <orchestrator_task_id>

# Create fixer task (depends on executor)
hermes kanban tasks create apmm-ut --title "Fixer: Fix test_abc.py" --profile ut-fixer --depends-on <executor_task_id>

# Verify blocking
hermes kanban tasks list apmm-ut --status pending
```

### Check Task Status

```bash
# List all tasks
hermes kanban tasks list apmm-ut

# View task details
hermes kanban tasks show apmm-ut <task_id>

# Check blocked tasks
hermes kanban tasks list apmm-ut --status blocked
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Gateway Process                 │
│                                                  │
│  ┌────────────────────────────────────────────┐│
│  │           Dispatcher (60s tick)             ││
│  │                                             ││
│  │  1. Query ready tasks from kanban.db       ││
│  │  2. Claim task via CAS                     ││
│  │  3. Spawn worker subprocess                ││
│  │     - Load profile SOUL.md                 ││
│  │     - Read task body                       ││
│  │     - Execute LLM inference                ││
│  │     - Call kanban_complete()               ││
│  │  4. Update task status                     ││
│  └────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
         │                           │
         v                           v
    kanban.db                   Hermes Agent
  (task state)                (worker process)
```

## File Paths

| Component | Path |
|-----------|------|
| Kanban DB | `C:\Users\admin\AppData\Local\hermes\kanban\boards\apmm-ut\kanban.db` |
| Orchestrator Profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-orchestrator\` |
| Executor Profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-executor\` |
| Fixer Profile | `C:\Users\admin\AppData\Local\hermes\profiles\ut-fixer\` |
| workflow.yaml | `D:\workspace\apmm\.agents\workflow.yaml` |

## Next Steps

1. ✅ Phase 2 完成：方案 A-1 集成（SKILL.md v5.2 + start_gateway.py + monitor_kanban.py）
2. 测试 Kanban 模式真实运行
3. 验证熔断器配置（failure_limit, error_rate_threshold）
4. 监控多 GPU 并行执行效率
5. 性能基准测试

## Kanban 模式触发入口

在 `workflow.yaml` 设置 `kanban.enabled: true`，加载 `ut/workflow` skill 后 Agent 自动：
1. 执行 `start_gateway.py` 启动 3 个 Gateway
2. 创建初始 Orchestrator 任务
3. 执行 `monitor_kanban.py` 监控进度

详见 [skills/ut/workflow/SKILL.md](../../../skills/ut/workflow/SKILL.md) § Kanban 模式执行步骤。

## References

- Hermes Kanban Docs: `C:\Users\admin\AppData\Local\hermes\docs\kanban.md`
- UT Workflow Skill: `skills/ut/workflow/SKILL.md`
- UT Progress: `tasks/ut/PROGRESS.md`