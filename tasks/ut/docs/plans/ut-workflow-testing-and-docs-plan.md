# UT Workflow测试与文档补充执行计划

**日期**: 2026-06-26
**来源**: Grilling深度审查结果
**目的**: 系统性解决UT workflow测试缺失和文档不完整问题

---

## 优先级排序（基于Grilling确认）

```
P0: 立即执行（阻塞交付）
  ↓
P1: 本周执行（影响效率）
  ↓  
P2: 下周执行（优化完善）
  ↓
P3: 废弃（dependency-resolver）
```

---

## P0任务清单（立即执行）

### Task 1: terminal-workflow单元测试

**文件**: `tests/ut/unit/test_terminal_workflow.py`

**测试内容**：
```python
def test_terminal_workflow_state_machine():
    """测试Linear模式状态定义"""
    states = ['idle', 'running', 'paused', 'completed', 'stopped', 'failed']
    # 验证状态转换逻辑

def test_terminal_workflow_stage_sequence():
    """测试Stage执行顺序（Stage1-6）"""
    expected_sequence = ['Stage1', 'Stage2', 'Stage3', 'Stage4', 'Stage5', 'Stage6']
    # 验证执行顺序

def test_terminal_workflow_interrupt_recovery():
    """测试中断恢复机制（建议补充）"""
    # 验证从last_completed_stage恢复

def test_terminal_workflow_handles_timeout():
    """测试包含超时任务的workflow（实际需求）"""
    # 验证超时测试处理逻辑
```

**优先级原因**：terminal-workflow通过命令行即可完成，是实际使用的主要通道

---

### Task 2: unit-test-collector单元测试

**文件**: `tests/ut/unit/test_unit_test_collector.py`

**测试内容**：
```python
def test_collect_tests_from_test_list():
    """测试从test_list.txt收集测试"""
    # 验证manifest.json初始化

def test_collect_tests_initializes_errors_and_failures():
    """测试初始化errors/failures字段"""
    # 验证初始状态

def test_collect_tests_extracts_test_names():
    """测试提取测试名称格式"""
    # 验证test_id格式（tests/xxx.py::test_func）
```

**优先级原因**：Stage1是workflow起点，manifest初始化错误会阻塞后续所有Stage

---

### Task 3: 状态机文档（已完成）

**文件**: `tasks/ut/docs/designs/linear-state-machine.md`（已创建，commit c14bf6c）

**包含内容**：
- 状态定义（idle/running/paused/completed/stopped/failed）
- 状态转换触发机制
- 用户状态处置指南
- 中断恢复机制说明

---

## P1任务清单（本周执行）

### Task 4: hermes-workflow关闭kanban测试

**文件**: `tests/ut/unit/test_hermes-workflow_linear.py`

**测试内容**：
```python
def test_hermes-workflow_linear_mode():
    """测试hermes-workflow关闭kanban模式（Linear equivalent）"""
    # 验证不使用Kanban调度
    # 验证直接调用hermes_runner

def test_hermes-workflow_handles_timeout():
    """测试包含超时任务（实际需求）"""
    # 验证超时测试处理
```

**优先级原因**：hermes-workflow关闭kanban是P1测试重点，优先于kanban端到端测试

---

### Task 5: workflow-loop-core wiring文档

**文件**: `skills/ut/workflow-loop-core/SKILL.md`（补充wiring章节）

**文档内容**：
```markdown
## Wiring文档

### Callbacks参数契约

terminal-workflow callbacks:
```python
{
    "check_state": check_terminal_state,
    "create_task": None,  # Linear不创建Kanban task
    "wait_complete": wait_terminal_stage_complete,
    "handle_failure": handle_terminal_failure,
    "update_state": update_terminal_workflow_state,
}
```

hermes-workflow callbacks:
```python
{
    "check_state": check_gateway_status,
    "create_task": kanban_task_creator.create_batch_task,
    "wait_complete": orchestrator_round.wait_for_tasks_complete,
    "handle_failure": orchestrator_round.handle_failure,
    "update_state": orchestrator_round.update_workflow_state,
}
```

### Linear vs Kanban wiring差异

| Callback | terminal-workflow | hermes-workflow |
|---|---|---|
| create_task | None | create_batch_task |
| wait_complete | wait_stage | wait_kanban_task |
| handle_failure | retry_stage | create_fixer_task |
```

**优先级原因**：理解wiring逻辑是解决stage依赖竞争、agent伪造输出等问题的关键

---

### Task 6: 错误处理增强（防止agent伪造）

**文件**: `skills/ut/unit-test-executor/scripts/execute_batch.py`（增强验证）

**增强内容**：
```python
def validate_batch_results(batch_results):
    """验证batch_results.json真实性"""
    # 检查remote_log_path是否真实存在
    # 检查pytest stdout是否完整
    # 检查统计数据是否一致（passed+failed+error=total）
    
    if not validate_remote_log(batch_results['remote_log_path']):
        raise ValidationError("Fabricated batch_results: remote_log missing")
```

**优先级原因**：agent伪造stage输出是实际发生的严重问题，需要增强验证机制

---

### Task 7: 架构修正（dependency-resolver废弃）

**文件**: `skills/ut/failure-handler/SKILL.md`（删除dependency-resolver描述）

**修正内容**：
```diff
- description: Worker Agent (核心) - 失败错误处理，分析失败原因、尝试修复代码、生成 handled_tests.json，由 Supervisor 调用执行 Stage 4（含 dependency-resolver 子 skill）
+ description: Worker Agent (核心) - 失败错误处理，分析失败原因、尝试修复代码、生成 handled_tests.json，由 Supervisor 调用执行 Stage 4

- │  • 调用 dependency-resolver 处理依赖缺失                    │
+ │  • 标记依赖缺失为 ignored（人工处理）                          │

删除 L2 层级："dependency-resolver"调用
```

**优先级原因**：文档不准确，dependency-resolver实际不调用且不需要（会使workflow低效）

---

## P2任务清单（下周执行）

### Task 8: hermes-workflow开启kanban端到端测试

**文件**: `tests/ut/integration/test_hermes-workflow_kanban.py`

**测试内容**：
```python
def test_hermes-workflow_kanban_full_flow():
    """测试完整链路：飞书→agent→Gateway→Workers"""
    # 模拟飞书webhook触发
    # 验证Kanban task创建
    # 验证Worker执行
    # 验证状态机转换
```

**优先级原因**：hermes-workflow kanban模式速度慢（多agent协同），实际不被优先使用，只需保证功能无问题

---

### Task 9: Watchdog超时根因记录

**文件**: `tasks/ut/docs/incidents/watchdog-timeout-analysis.md`

**记录内容**：
- 现象：300s watchdog SIGKILL
- 可能原因：测试本身慢/GPU资源不足/Bastion断联/Docker配置
- 不需要解决（只记录）

**优先级原因**：只需记录，不调整timeout配置

---

### Task 10: Blocked task机制理解

**文件**: `tasks/ut/docs/designs/kanban-task-creation-mechanism.md`

**理解内容**：
- 任务创建机制（kanban_task_creator.py）
- Blocked task触发条件
- 任务处理机制（orchestrator_round.py）

**优先级原因**：偶尔发生blocked task，理解机制有助于手动处理

---

## P3废弃清单（无需执行）

### dependency-resolver相关

- ❌ 测试（test_dependency_resolver.py）- 废弃
- ❌ 文档补充 - 废弃
- ❌ 实现补充 - 废弃

**废弃原因**：会使workflow执行低效，实际不调用

---

## 执行顺序建议

**Week 1 (P0)**：
```
Day 1-2: Task 1-2（单元测试）
Day 3:   Task 3（状态机文档 - 已完成）
Day 4-5: Review + Fix
```

**Week 2 (P1)**：
```
Day 1-2: Task 4-5（hermes测试 + wiring文档）
Day 3-4: Task 6-7（错误处理 + 架构修正）
Day 5:   Review + Fix
```

**Week 3 (P2)**：
```
Day 1-2: Task 8（kanban端到端）
Day 3-4: Task 9-10（记录 + 理解）
Day 5:   Review + 总结
```

---

## Git commits记录

| Commit | 任务 | 状态 |
|---|---|---|
| c14bf6c | Task 3：状态机文档 | ✅ 已完成 |
| de21e34 | 一键启动脚本+测试骨架 | ✅ 已完成 |
| 2fce098 | agents架构文档 | ✅ 已完成 |
| a94c5a6 | PYTHONPATH fix | ✅ 已完成 |

---

**下一步行动**：立即执行Task 1-2（单元测试），或在新session继续P0-P1任务。

