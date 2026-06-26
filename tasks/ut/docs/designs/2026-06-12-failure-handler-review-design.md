# Failure-Handler Stage Review Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 确认 failure-handler stage 的 10 个设计决策，确保架构完善

**Context:** 对 skills/ut/failure-handler/SKILL.md (v2.1) 进行全面 brainstorming review

---

## 决策汇总

| # | 问题 | 决策 |
|:-:|------|------|
| 1 | 错误分类规则 | **两阶段**：先关键词匹配，不确定时 LLM 判断 |
| 2 | retry_test 机制 | **单测试 retry + 标记 fixed_pending_verify**，下一轮批量验证 |
| 3 | dependency-resolver 状态 | **已实现**（3 个脚本），无需修改 |
| 4 | 代码修改安全 | **自动应用 patch + 阈值保护**（失败多次自动 ignored） |
| 5 | Agent 判断可靠性 | **保持现状 + 阈值保护**，无需额外置信度评估 |
| 6 | 超时控制 | **分批处理**：每轮最多 10 个失败测试 |
| 7 | resource 恢复机制 | **保持 ignored**，workflow 结束后汇总供用户处理 |
| 8 | ignored 阈值 | **GOAL.md 定义 ≤50%**，超过则 workflow 未完成 |
| 9 | batch vs test 级别 | **test 级别 + 缓存**，已处理依赖不重复调用 |
| 10 | 状态一致性 | **单一数据源**：stats 从 manifest.json 读取 |

---

## 详细决策说明

### Decision 1: 错误分类规则（两阶段）

**问题**：关键词匹配可能误判（如 "ModuleNotFoundError" 可能是代码 bug 导致的 import 错误）

**决策**：
```
Step 1: 关键词匹配
  ├─ 匹配成功 → 执行对应处理
  └─ 匹配失败/不确定 → Step 2

Step 2: LLM 判断
  ├─ 提供：错误消息 + 测试代码片段 + 上下文
  └─ LLM 返回：错误类型 + 理由
```

**关键词规则**（保持现有）：
- `dependency`: ModuleNotFoundError, ImportError
- `network`: timeout, ConnectionError
- `resource`: CUDA out of memory, OOM, NCCL
- `version`: TypeError, AttributeError
- `functional`: AssertionError, ValueError
- `download_error`: Failed to download, Model not found
- `other`: 不匹配以上

---

### Decision 2: retry_test 机制（单测试 + 标记待观察）

**问题**：修复后如何验证？单测试（快但无副作用检查）vs 批量（慢但安全）

**决策**：
```
修复代码 → 单测试 retry → passed?
                          ├─ yes → 标记 fixed_pending_verify
                          └─ no → 保持 failed，尝试其他修复

下一轮 batch 执行时：
  batch-selector 同时选择：
    ├─ pending 测试（正常流程）
    └─ fixed_pending_verify 测试（批量验证）

  执行后：
    ├─ 批量验证 passed → 最终改为 passed
    └─ 批量验证 failed → 改为 failed，重新触发 failure-handler
```

**manifest.json 新增状态**：
```json
{
  "status": "fixed_pending_verify",
  "previous_status": "failed",
  "fix_description": "修复描述",
  "fix_timestamp": "2026-06-12T14:30:00Z"
}
```

---

### Decision 3: dependency-resolver 状态

**验证结果**：已实现（v1.0.0），包含 3 个核心脚本：
- `download_model.py`
- `install_package.py`
- `check_dependency.py`

**无需修改**，failure-handler 可直接调用。

---

### Decision 4: 代码修改安全（自动应用 + 阈值保护）

**问题**：自动修改代码可能引入新问题，无回滚机制

**决策**：
```
patch diff 写入 handled_tests.json
     ↓
自动应用 patch
     ↓
执行 retry batch（单测试或小批次）
     ↓
结果判断：
  ├─ passed → 标记 passed ✅
  ├─ failed → 记录失败次数
  │            失败次数 < 阈值(3 次) → 重新分析生成新 patch
  └─ 失败次数 >= 阈值 → 标记 ignored（放弃）
```

**阈值配置**：
- `workflow.yaml stages.handle_failures.max_retry_per_test: 3`

---

### Decision 5: Agent 判断可靠性

**问题**：LLM 可能误判错误类型

**决策**：保持现状，依赖"失败多次自动放弃"机制保护

**理由**：
- 失败后会重新分析（迭代修正）
- 阈值保护防止无限尝试
- 增加置信度评估会增加复杂度和成本

---

### Decision 6: 超时控制（分批处理）

**问题**：Stage 4 timeout=900s，但 50 个失败测试可能超时

**决策**：
- 每轮最多处理 N 个失败测试（如 10 个）
- 剩余失败测试留到下一轮
- batch-selector 下一轮会再次选择 pending 的 failed 测试

**配置**：
```yaml
stages:
  handle_failures:
    timeout: 900
    max_failed_per_iteration: 10
```

---

### Decision 7: resource 恢复机制

**问题**：GPU OOM 可能是临时状态，标记 ignored 后永不重试

**决策**：保持 `ignored`，workflow 结束后汇总 resource 问题供用户处理

**汇总格式**（workflow 结束时）：
```
Resource Issues Summary:
- 5 tests ignored due to CUDA OOM
- 2 tests ignored due to NCCL error
建议：检查 GPU 使用情况，调整 batch_size 或 CUDA_VISIBLE_DEVICES
```

---

### Decision 8: ignored 阈值

**问题**：多少 ignored 才算"完成"？

**决策**：在 GOAL.md 定义 ignored 阈值 ≤50%

**理由**：
- vLLM 测试环境复杂，环境问题可能较多
- 宽松阈值先跑能跑的测试
- ignored 测试后续单独处理

---

### Decision 9: batch vs test 级别处理

**问题**：同一 batch 多个测试可能因同一原因失败（如同一模型缺失）

**决策**：保持 test 级别处理，但增加缓存机制

**缓存实现**：
```python
# 在 workflow_state.json 或内存中维护
resolved_dependencies = {
    "meta-llama/Llama-3.2-1B": "resolved",
    "transformers>=4.40.0": "resolved"
}

# 处理测试时先检查缓存
if dependency in resolved_dependencies:
    skip_dependency_resolver_call()
```

---

### Decision 10: 状态一致性

**问题**：manifest.json 和 workflow_state.json 的 stats 可能不一致

**决策**：单一数据源 —— workflow_state.json 的 stats 直接从 manifest.json 读取

**实现**：
```python
# workflow_state.json 不单独存储 stats
# 每次需要统计时，从 manifest.json 计算
manifest = json.loads(Path(manifest_path).read_text())
state["stats"] = manifest["statistics"]
```

---

## 需修改的文件

| 文件 | 修改内容 |
|------|----------|
| `skills/ut/failure-handler/SKILL.md` | 更新决策 1-9 的描述 |
| `tasks/ut/GOAL.md` | 增加 ignored 阈值 ≤50% |
| `skills/ut/terminal-workflow/scripts/init_workflow_state.py` | 决策 10：stats 从 manifest 读取 |
| `.agents/workflow.yaml` | 增加 `max_failed_per_iteration: 10`, `max_retry_per_test: 3` |

---

## 不修改的文件

- `skills/ut/dependency-resolver/` — 已实现，无需修改

---

*创建日期: 2026-06-12*
*版本: 1.0.0*