# UT Workflow 数据流一致性审查报告

**日期**: 2026-07-12
**审查范围**: UT Workflow 全部脚本与 SKILL.md 文档
**审查结论**: 架构断裂 — `test_load` 概念从未被实际脚本接入，manifest.json 是事实上的单一数据源

---

## 1. 核心发现：test_load 架构断裂

### 1.1 问题描述

`terminal-workflow/SKILL.md` 和 `hermes-workflow/SKILL.md` 的 Stage 1 描述了一个 `test_load` 数据流：
1. `generate_test_load.py` 从 manifest 抽取指定数量 test 生成 `test_load_xxx.json`
2. 后续 batch 执行基于 test_load（而非完整 manifest）
3. `update_batch_state.py` 在 batch 完成时更新 test_load + workflow_state
4. `update_manifest_from_test_load.py` 在全部完成后一次性回写 manifest

**但实际脚本行为完全不同**：所有 worker 脚本（Stage 2-5）直接读写 `manifest.json`，`test_load` 在整个循环中从未被读取或更新。

### 1.2 数据流追踪

#### Single-phase 数据流

| 步骤 | SKILL.md 描述 | 实际脚本行为 | 一致？ |
|------|-------------|------------|--------|
| Stage 1.0: 测试收集 | unit-test-collector 生成 manifest.json | collect.py 存在但 SKILL.md 未引用脚本名 | ⚠️ |
| Stage 1.5: test_load 生成 | generate_test_load.py 从 manifest 抽取 | ✅ 脚本存在且行为正确 | ✅ |
| Stage 2: batch 选择 | batch-selector 读 test_load | generate_batch.py 读 manifest.json | ❌ 读错文件 |
| Stage 3: 测试执行 | execute_batch.py 远程 pytest | ✅ 脚本存在且行为正确 | ✅ |
| Stage 4: 失败处理 | failure-handler 处理 failed | generate_handled_manifest.py 读 batch_results.json | ✅ |
| Stage 5: 状态更新 | manifest-updater 更新 test_load + workflow_state | update_status.py / update_manifest.py 更新 manifest.json | ❌ 写错文件 |
| Batch 完成时 | update_batch_state.py 更新 test_load + workflow_state | single-phase 下不调用 | ❌ 未接入 |
| Post-loop | update_manifest_from_test_load.py 回写 manifest | ✅ 脚本存在 | ✅ |

**结论**: single-phase 模式下，test_load 在整个循环中从未被读取或更新。batch-selector 从 manifest 选 test，manifest-updater 更新 manifest。test_load 停留在初始状态（全 pending）。

#### Two-phase 数据流

| 步骤 | SKILL.md 描述 | 实际脚本行为 | 一致？ |
|------|-------------|------------|--------|
| Phase 1: 批量执行 | auto_run_batches_two_phase.py | ✅ 脚本存在 | ✅ |
| Phase 1 内部 Stage 1-2 | generate_batch.py 选 test | 读 manifest.json | ❌ 未用 test_load |
| Phase 1 内部 Stage 4 | update_manifest.py 更新状态 | 更新 manifest.json | ❌ 未更新 test_load |
| Phase 1 Stage 4.5 | update_batch_state.py 更新 test_load | 仅在 two-phase 调用 | ⚠️ |
| Phase 2 Stage 1 | phase2_stage1_analyze.py 读 test_load | 脚本已删除（仅存 .pyc） | ❌ |
| 人工决策 | user_decision.json | 无脚本创建 | ⚠️ 需 agent 凑 |
| Phase 2 Stage 2 | phase2_stage2_retry.py | 脚本已删除（仅存 .pyc） | ❌ |
| Post-loop | update_manifest_from_test_load.py | ✅ 脚本存在 | ✅ |

**结论**: two-phase 模式下，Phase 1 的内部 Stage 1-4 仍然操作 manifest.json。Phase 2 脚本已被删除。

### 1.3 矛盾的权威声明

| SKILL.md | 声明 | 与 test_load 矛盾？ |
|----------|------|-------------------|
| two-phase-handler | "Manifest is the single source of truth" | ✅ 矛盾 |
| manifest-updater | "manifest.json MUST be written through update_status.py" | ✅ 矛盾 |
| failure-handler | "manifest-centric: 所有数据从 manifest 读取" | ✅ 矛盾 |
| batch-selector | "从 manifest.json 选择 pending + fixed_pending_verify 测试" | ✅ 矛盾 |
| terminal-workflow | "后续batch执行基于此清单（而非完整manifest）" | — 此处声明 test_load |
| hermes-workflow | 同上 | — 此处声明 test_load |

**4 个 Worker SKILL.md 声明 manifest 为唯一数据源，2 个 Channel SKILL.md 声明 test_load 为工作数据源。**

---

## 2. 脚本一致性问题

### 2.1 manifest-updater 有两个功能重叠的脚本

| 脚本 | v5 合并逻辑 | Schema 校验 | 远程日志审计 | workflow_state 集成 |
|------|-----------|-----------|-----------|-----------------|
| `update_manifest.py` | ✅ `update_manifest()` | ❌ 无 | ❌ 无 | ❌ 无 |
| `update_status.py` | ❌ 无（仅 legacy `batch_update_status`） | ✅ `validate_and_write` | ✅ `audit_batch_results` | ✅ `update_from_workflow_state` |

**问题**: v5 逻辑（retry_count 跟踪、retriable_error→ignored 提升、handled_tests 覆盖）只在 `update_manifest.py` 中，但 schema 校验和审计只在 `update_status.py` 中。两者从未同时生效。

### 2.2 auto_run_batches_two_phase.py 调用错误的更新路径

```python
# auto_run_batches_two_phase.py Stage 4 调用:
cmd = [sys.executable, ".../update_manifest.py", "--manifest-path", ..., "--batch", ...]
```

这走的是 `update_manifest.py` 的 legacy `batch_update_from_results()` 路径：
- ❌ 无 v5 retry_count 跟踪
- ❌ 无 schema 校验
- ❌ 无远程日志审计
- ❌ 无 handled_tests.json 合并

### 2.3 已删除的 Phase 2 脚本

`phase2_stage1_analyze.py` 和 `phase2_stage2_retry.py` 的 `.py` 文件已删除，但 `.pyc` 仍在 `__pycache__` 中。`two-phase-handler/SKILL.md` 仍以内联代码形式描述 Phase 2 逻辑。

### 2.4 test_load 相关脚本是死代码

| 脚本 | 状态 | 原设计用途 | 实际调用情况 |
|------|------|----------|-----------|
| `generate_test_load.py` | 存在 | 从 manifest 抽取 test 子集 | 仅 Channel SKILL.md Stage 1 引用，loop 中不使用 |
| `update_batch_state.py` | 存在 | batch 完成时更新 test_load + workflow_state | 仅 two-phase Stage 4.5 引用，single-phase 不调用 |
| `update_manifest_from_test_load.py` | 存在 | test_load 完成后回写 manifest | 仅 Channel SKILL.md post-loop 引用，实际 loop 中 manifest 已被直接更新 |

---

## 3. 修复方案

### 3.1 架构决策：manifest.json 为唯一数据源

基于以下理由：
1. 4 个 Worker SKILL.md 的 HARD CONTRACT 均声明 manifest 为唯一数据源
2. 所有 worker 脚本已基于 manifest 运行并通过实际测试
3. `two-phase-handler` HARD CONTRACT 明确："Manifest is the single source of truth"
4. test_load 概念增加了架构复杂度但从未被实际接入
5. 26MB manifest 的 JSON 读写性能足够（单次 <1s）

### 3.2 脚本变更

| 操作 | 脚本 | 原因 |
|------|------|------|
| **合并** | `update_manifest.py` → `update_status.py` | 将 v5 合并逻辑迁入 update_status.py，统一为唯一 manifest writer |
| **删除** | `update_manifest_from_test_load.py` | test_load 回写逻辑不再需要（manifest 已被直接更新） |
| **删除** | `update_batch_state.py` | test_load 更新逻辑不再需要；workflow_state 更新已在 update_status.py 中 |
| **重定向** | `generate_test_load.py` | 改为可选的 manifest 预过滤工具（生成筛选后的 manifest 副本，而非平行数据集） |
| **修复** | `auto_run_batches_two_phase.py` | Stage 4 改为调用 `update_status.py --workflow-state` |
| **清理** | `__pycache__/phase2_*.pyc` | 删除已删除脚本的编译缓存 |

### 3.3 文档变更

| 文档 | 变更 |
|------|------|
| `terminal-workflow/SKILL.md` | 删除 Stage 1 test_load 生成节，明确 manifest 为唯一数据源 |
| `hermes-workflow/SKILL.md` | 同上 |
| `manifest-updater/SKILL.md` | 明确 `update_status.py` 为唯一 writer，移除 `update_manifest.py` 引用 |
| `two-phase-handler/SKILL.md` | 修正脚本引用，移除已删除脚本 |
| `batch-selector/SKILL.md` | 确认已正确（读 manifest） |

---

## 4. 需 Agent 介入的逻辑点（文档中需强调）

以下逻辑无法完全脚本化，需 Agent 在执行时进行判断：

1. **Phase 2 人工决策**: `user_decision.json` 需人工创建，SKILL.md 需提供完整 schema 和示例
2. **failure-handler L5/L6**: Agent 需理解 traceback 上下文，判断问题来源（test vs vllm），生成修复 patch
3. **dependency-stall 分类**: Agent 需将 log 尾部喂给 LLM 进行分类
4. **terminal-workflow 逐 stage 执行**: Agent 需在每 stage 后检查 STAGE COMPLETED 输出，不可批量自动化

---

*报告生成时间: 2026-07-12*
*审查人: AI Agent (data-flow audit)*
