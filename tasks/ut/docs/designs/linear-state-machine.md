# Terminal Workflow状态机文档

**日期**: 2026-06-26
**目的**: 定义terminal-workflow状态 + 用户状态处置指南

---

## 1. 状态定义

| 状态 | 说明 | Stage范围 | 可转换到 |
|---|---|---|---|
| `idle` | 初始状态 | 无 | `running` |
| `running` | 执行中 | Stage1-6 | `paused`, `completed`, `failed`, `stopped` |
| `paused` | 用户暂停 | 当前Stage | `running`, `stopped` |
| `completed` | 全部测试通过 | Stage6完成 | 无（终态） |
| `stopped` | 用户停止 | 任意Stage | 无（终态） |
| `failed` | Stage失败 | 失败Stage | `running`（retry） |

---

## 2. 状态转换触发

| 触发 | 当前状态 | 新状态 | 说明 |
|---|---|---|---|---|
| 启动workflow | `idle` | `running` | 开始Stage1 |
| Stage完成 | `running` | `running` | 进入下一Stage |
| 全部Stage完成 | `running` | `completed` | 所有测试通过 |
| Stage失败 | `running` | `failed` | Stage执行错误 |
| Retry | `failed` | `running` | 从失败Stage重新执行 |
| 用户暂停 | `running` | `paused` | 暂停当前Stage |
| 用户恢复 | `paused` | `running` | 继续当前Stage |
| 用户停止 | `running`/`paused` | `stopped` | 终止workflow |

---

## 3. 用户状态处置指南

### 状态：running

**现象**：workflow正在执行Stage1-6

**用户无需介入**，等待workflow完成。

**检查进度**：
- 查看workflow_state.json：`iteration`, `stats`
- 查看飞书进度卡片（如有）

---

### 状态：paused

**现象**：workflow被用户暂停

**处置方式**：

A. **恢复执行**：
```bash
# 向agent发送命令
"继续workflow"
```

B. **停止workflow**：
```bash
# 向agent发送命令
"停止workflow"
```

---

### 状态：failed

**现象**：某个Stage执行失败

**处置方式**：

A. **Retry重试**：
```bash
# 向agent发送命令
"retry workflow"
# agent从失败Stage重新执行
```

B. **手动检查**：
- 查看run_dir/logs/下的日志文件
- 定位失败原因（Stage脚本错误、bastion断联等）
- 手动修复问题后retry

C. **停止workflow**：
```bash
# 向agent发送命令
"停止workflow"
```

---

### 状态：completed

**现象**：所有测试通过，workflow完成

**处置方式**：

A. **查看结果**：
- 查看run_dir/manifest.json：最终测试状态
- 查看workflow_state.json：`stats`

B. **清理run_dir**（可选）：
```bash
# 归档或删除run_dir
```

---

### 状态：stopped

**现象**：用户主动停止workflow

**处置方式**：

A. **确认停止**：
- workflow_state.json状态为stopped
- 无法恢复，需重新启动

B. **重新启动**（如需要）：
```bash
# 向agent发送命令
"启动workflow --workflow-yaml xxx.yaml"
```

---

## 4. 中断恢复机制

**问题**：terminal-workflow当前缺少中断恢复机制

**现状**：
- agent会话断开 → workflow状态丢失
- 无法从last_completed_stage恢复
- 需要手动重新启动workflow

**建议改进**：
```python
def init_or_resume(workflow_yaml):
    if workflow_state.json存在:
        last_stage = workflow_state['last_completed_stage']
        resume_from_stage(last_stage + 1)
    else:
        start_from_stage(1)
```

---

## 5. 与hermes-workflow状态对比

| 状态 | terminal-workflow | hermes-workflow |
|---|---|---|---|
| running | 有 | 有 |
| paused | 有 | 有 |
| completed | 有 | 有 |
| stopped | 有 | 有 |
| failed | 有 | 有 |
| waiting_otp | 无 | 有（Bastion OTP） |

**关键差异**：
- terminal-workflow无waiting_otp状态（手动Bastion管理）
- hermes-workflow有完整状态机（含OTP自动恢复）

---

**文档生成**: 2026-06-26
