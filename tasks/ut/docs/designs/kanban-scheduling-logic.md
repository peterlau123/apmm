# Kanban调度逻辑文档

**日期**: 2026-06-26
**目的**: 补充kanban_task_creator.py + orchestrator_round.py逻辑文档

## 核心逻辑

### kanban_task_creator.py
- 输入: manifest_path, batch_size
- 输出: Kanban task (t_xxx)
- 逻辑: 选择pending tests → 创建task → 设置依赖链

### orchestrator_round.py
- 状态: waiting_otp → running → fixing → continue → completed
- 逻辑: 检查Gateway → 检查running tasks → 创建batch → 等待完成 → 更新manifest

## 调用示例

```bash
python start_ut_workflow.py --tier L4 --mode kanban --auto-create-task
```
