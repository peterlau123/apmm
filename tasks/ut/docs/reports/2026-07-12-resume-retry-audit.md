# Resume / Retry 逻辑审查报告

**分支**: test/check-resume-retry
**日期**: 2026-07-12
**范围**: resume 续跑、test-level retry、workflow-level retry

---

## 1. Resume（续跑）逻辑

### 1.1 当前流程

`
ut_runner.init_or_resume(yaml, resume_from)
  -> resume_from 有值: 读 workflow_state.json, 返回 (run_dir, state, iteration)
  -> resume_from 为空: 调用 init_workflow_state.py 创建新 run
`

### 1.2 发现的问题

| # | 严重性 | 问题 | 影响 |
|---|--------|------|------|
| R1 | **P0** | init_or_resume resume 时不检查 test_load 是否存在 | 如果 test_load 文件丢失或路径过期，进入循环后 generate_batch.py 崩溃 |
| R2 | **P0** | auto_run_batches_two_phase.py resume 时不检查 test_load | 从 checkpoint 恢复后第一个 batch 的 generate_batch.py 崩溃 |
| R3 | **P1** | generate_test_load.py 无 skip-if-exists 逻辑 | SKILL.md 说"resume 时跳过"，但脚本不支持；重复调用会创建新文件，丢失进度 |
| R4 | **P2** | workflow_state_manager.resume_info 不包含 test_load 信息 | resume_info 只记录 last_batch_id，不记录 test_load 路径和完成状态 |

### 1.3 修复建议

- R1/R2: 在 init_or_resume 和 auto_run_batches 的 resume 路径中，检查 workflow_state.paths.test_load 是否存在，不存在则报错
- R3: generate_test_load.py 添加 --skip-if-exists 参数，检查 workflow_state 中已有的 test_load 路径

---

## 2. Test-level Retry（单测试重试）逻辑

### 2.1 设计意图（v5 规则）

- merge_batch_results: failed/retriable_error/error -> retry_count += 1
- retriable_error + retry_count >= max_retry -> promoted to ignored
- _is_selectable: retriable_error/failed 可选（当 retry_count < max_retry）
- select_batch: 按 priority 排序 (pending=1, fixed_pending_verify=2, retriable_error=3, failed=4)

### 2.2 发现的问题

| # | 严重性 | 问题 | 影响 |
|---|--------|------|------|
| T1 | **P0** | generate_batch() 不使用 select_batch() | v5 选择逻辑（含 retriable_error/failed）定义了但从未调用；实际用的是内联过滤，只选 pending + fixed_pending_verify |
| T2 | **P0** | retriable_error/failed 测试永远不会被重选 | 因为 T1，failed 和 retriable_error 状态的测试永远不会出现在新 batch 中 |
| T3 | **P1** | retry_count 跟踪无效 | merge_batch_results 递增 retry_count，但由于 T1/T2，retry_count 永远不会被检查到 max_retry |
| T4 | **P1** | retriable_error -> ignored 提升永远不会自然触发 | 因为 retriable_error 测试不会被重选执行，retry_count 不会继续增长 |

### 2.3 根因

generate_batch.py 中存在两套并行实现：
- select_batch() (v5, 正确但未使用) - 支持 pending/fixed_pending_verify/retriable_error/failed
- generate_batch() 内联过滤 (legacy, 实际使用) - 只支持 pending/fixed_pending_verify

### 2.4 修复建议

- 将 generate_batch() 的内联过滤替换为调用 select_batch()
- 或将 select_batch() 的逻辑合并到 generate_batch() 中

---

## 3. Workflow-level Retry（整批重跑）逻辑

### 3.1 当前流程

`
Workflow 停止后 (completed/stopped/error_threshold)
  -> 用户请求"重跑失败的 batch"
  -> 调用 two-phase-handler SKILL
    -> Phase 2 Stage 1: 统计分析 (读 test_load, 按 error_type 分类)
    -> 人工决策 (user_decision.json)
    -> Phase 2 Stage 2: 执行重试
  -> Post-loop: update_manifest_from_test_load.py 回写 manifest
`

### 3.2 发现的问题

| # | 严重性 | 问题 | 影响 |
|---|--------|------|------|
| W1 | **P0** | two-phase-handler HARD CONTRACT 规则 3 仍写"Manifest is the single source of truth" | 与新架构矛盾（test_load 是工作数据集）；Phase 2 应读 test_load |
| W2 | **P1** | Phase 2 脚本已删除 | phase2_stage1_analyze.py 和 phase2_stage2_retry.py 的 .py 文件不存在，SKILL.md 仅有内联代码 |
| W3 | **P2** | user_decision.json 无创建/校验脚本 | 人工决策 checkpoint 有 schema 但需 agent 手动创建 |

### 3.3 修复建议

- W1: 修改 two-phase-handler HARD CONTRACT 规则 3 为"test_load is the working dataset"
- W2: 要么恢复 Phase 2 脚本，要么在 SKILL.md 中明确标注"Agent 按内联代码执行"
- W3: 添加 create_user_decision.py 脚本或明确标注为人工创建

---

## 4. 汇总

| 类别 | P0 | P1 | P2 | 总计 |
|------|----|----|-----|------|
| Resume | 2 | 1 | 1 | 4 |
| Test retry | 2 | 2 | 0 | 4 |
| Workflow retry | 1 | 1 | 1 | 3 |
| **合计** | **5** | **4** | **2** | **11** |

### 最严重问题 (P0)

1. **T1/T2**: generate_batch() 不使用 v5 select_batch()，retriable_error/failed 测试永远不会被重选
2. **R1/R2**: resume 时不检查 test_load 是否存在
3. **W1**: two-phase-handler HARD CONTRACT 仍声明 manifest 为唯一数据源

---

*审查人: test/check-resume-retry 分支*
*审查时间: 2026-07-12*
