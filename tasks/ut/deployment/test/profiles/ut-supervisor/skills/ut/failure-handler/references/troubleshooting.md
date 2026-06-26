# failure-handler 问题解决手册

## 核心原则

> **重要**：所有错误类型都**不能直接 ignored**，必须先尝试解决，记录 attempts，达到阈值后才 ignored。

**分层处理架构**：

| 层级 | 处理方式 | 适用任务 |
|------|----------|----------|
| L1 脚本规则 | 关键词匹配、阈值判断 | GPU检测、延时重试、计数 |
| L2 脚本调用 | 调用已有脚本 | dependency-resolver |
| L4 脚本统计 | 数学运算 | attempts计数、阈值判断 |
| L5 Agent判断 | 需理解上下文 | 问题来源分析、可修复性评估 |
| L6 Agent生成 | 需代码理解 | 修复patch生成 |

**关键原则**：
- 确定性任务用脚本（GPU检测、延时重试、计数）
- Agent 只处理需要理解的任务（问题来源分析、代码修复）

---

## 常见问题处理流程

### NCCL通信失败

**错误**: `RuntimeError: NCCL error: unhandled cuda error`

**尝试解决**（脚本 + Agent）：

1. **脚本检测GPU状态** (L1)
2. **脚本延时重试** (L1) - [5s, 10s, 20s]
3. **脚本降低并行度** (L1)
4. **Agent判断是否环境问题** (L5)
5. **脚本标记 ignored** (L4) - attempts >= 3

### 模型下载失败

**错误**: `OSError: cannot connect to huggingface.co`

**尝试解决**：

1. **脚本检查HF cache** (L1)
2. **脚本调用 dependency-resolver** (L2)
3. **Agent选择替代模型** (L5)
4. **脚本标记 ignored** (L4)

### 代码修复失败

**尝试解决**：

1. **Agent生成patch** (L6)
2. **脚本验证修复** (L2)
3. **Agent生成替代方案** (L6)
4. **脚本标记 ignored** (L4)

---

*创建日期: 2026-06-14*