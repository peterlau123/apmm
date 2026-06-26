# Failure-Handler Stage Review: Implementation Analysis

> **Goal:** Analyze 10 design decisions for implementation difficulty, skill/workflow impact, and prioritization

**Deep dive focus:** Decisions 2, 6, 10 (highest complexity and cross-skill coordination)

---

## Section 1: Summary Comparison Table

| # | Decision | Difficulty | Skills Changed | Workflow Impact | Risk Level |
|:-:|----------|:----------:|----------------|:---------------:|:----------:|
| 1 | 错误分类规则（两阶段） | 🟡 Medium | failure-handler | 🟢 Low | 🟢 Low |
| 2 | retry_test机制 | 🔴 **High** | failure-handler + batch-selector + workflow + schema | 🔴 **High** | 🔴 **High** |
| 3 | dependency-resolver状态 | 🟢 Low | None (verified) | 🟢 None | 🟢 None |
| 4 | 代码修改安全 | 🟡 Medium | failure-handler + workflow.yaml | 🟡 Medium | 🟡 Medium |
| 5 | Agent判断可靠性 | 🟢 Low | None | 🟢 None | 🟢 None |
| 6 | 超时控制 | 🔴 **Medium-High** | failure-handler + workflow.yaml | 🔴 **Medium-High** | 🟡 Medium |
| 7 | resource恢复机制 | 🟢 Low | workflow (end only) | 🟢 Low | 🟢 Low |
| 8 | ignored阈值 | 🟢 Low | GOAL.md only | 🟢 None | 🟢 None |
| 9 | batch vs test级别 | 🟡 Medium | workflow_state + failure-handler | 🟡 Medium | 🟡 Medium |
| 10 | 状态一致性 | 🔴 **High** | workflow + all stats readers | 🔴 **High** | 🟡 **Medium-High** |

**Legend:**
- 🟢 Low/None: Single skill change, no workflow flow change
- 🟡 Medium: 1-2 skills, minor workflow adjustment
- 🔴 High: 3+ skills, state machine changes, cross-stage coordination

---

## Section 2: Decision-by-Decision Analysis

### Decision 1: 错误分类规则（两阶段）

**Problem:** 关键词匹配可能误判（如 `ModuleNotFoundError` 可能是代码 bug 导致的 import 错误）

**Solution:**
```
Step 1: 关键词匹配
  ├─ 匹配成功 → 执行对应处理
  └─ 匹配失败/不确定 → Step 2

Step 2: LLM 判断
  ├─ 提供：错误消息 + 测试代码片段 + 上下文
  └─ LLM 返回：错误类型 + 理由
```

**Implementation:**
- Add `classify_error_two_stage()` function in failure-handler
- Keywords remain unchanged (6 types)
- New LLM fallback path with structured prompt

**Skill Impact:**
- `failure-handler/SKILL.md`: Add two-stage classification logic (≈20 lines)
- No changes to batch-selector, workflow, manifest-updater

**Workflow Impact:**
- 🟢 Low: Internal to failure-handler stage
- No changes to state machine, loop flow, or downstream stages

**Risk:**
- 🟢 Low: Additive feature, existing keyword path unchanged
- LLM fallback is opt-in (only when keywords don't match)

---

### Decision 2: retry_test机制（单测试 + 标记待观察）【DEEP DIVE】

**Problem:** 修复后如何验证？单测试（快但无副作用检查）vs 批量（慢但安全）

**Solution:**
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

**Implementation Complexity Analysis:**

| Component | Change Required | Complexity |
|-----------|-----------------|------------|
| manifest_schema.json | Add `fixed_pending_verify` status enum | Low |
| batch-selector | Filter `pending OR fixed_pending_verify` | Medium |
| manifest-updater | Handle `fixed_pending_verify → passed/failed` transition | Medium |
| failure-handler | Write `fixed_pending_verify` + fix_details | Medium |
| workflow.yaml | Document new status semantics | Low |

**Detailed Impact on Skills:**

**2.1 batch-selector Changes:**
```python
# Current: 只选 pending
pending_tests = [t for t in manifest["tests"] if t.get("status") == "pending"]

# New: 选 pending + fixed_pending_verify
pending_tests = [t for t in manifest["tests"]
                 if t.get("status") in ["pending", "fixed_pending_verify"]]

# 区分优先级：pending 优先，fixed_pending_verify 作为验证批次
normal_pending = [t for t in pending_tests if t["status"] == "pending"]
verify_pending = [t for t in pending_tests if t["status"] == "fixed_pending_verify"]

# batch_config 标记验证批次
if verify_pending:
    batch_config["verification_batch"] = True
    batch_config["verification_tests"] = verify_pending[:batch_size]
```

**2.2 manifest-updater Changes:**
```python
# 处理 fixed_pending_verify 测试的批量验证结果
if test["status"] == "fixed_pending_verify" and batch_result["status"] == "passed":
    test["status"] = "passed"  # 最终通过
    test["fix_verified"] = True
elif test["status"] == "fixed_pending_verify" and batch_result["status"] != "passed":
    test["status"] = "failed"  # 验证失败，回到 failed
    test["previous_status"] = "fixed_pending_verify"
    # 不删除 fix_details，保留修复历史
```

**2.3 New State Transition:**
```
pending → running → passed (正常流程)
                 → failed → fixed_pending_verify → passed (修复成功)
                                        → failed (验证失败)
                 → error → ignored (不可修复)
                 → ignored (跳过)
```

**Workflow Impact:**
- 🔴 **High**: New state in state machine
- batch-selector needs to handle two types of "pending"
- manifest-updater needs to handle verification result transitions
- Loop continues until `pending + fixed_pending_verify == 0`

**Risk Assessment:**
- 🔴 **High Risk Factors:**
  1. **State machine complexity**: New state adds 2 new transitions
  2. **Cross-stage coordination**: batch-selector + manifest-updater must agree on semantics
  3. **Edge case**: fixed_pending_verify test fails → should it trigger failure-handler again?
  4. **Data consistency**: If batch crashes, fixed_pending_verify tests might be stuck

**Mitigation Strategies:**
1. Limit `fixed_pending_verify` tests per batch (e.g., max 10)
2. Add timeout for stuck tests (e.g., 2 iterations without verification → back to failed)
3. Add `fix_verified_at` timestamp for auditing

---

### Decision 3: dependency-resolver状态

**Verification Result:**
- `skills/ut/dependency-resolver/scripts/download_model.py` ✅ exists
- `skills/ut/dependency-resolver/scripts/install_package.py` ✅ exists
- `skills/ut/dependency-resolver/scripts/check_dependency.py` ✅ exists

**Implementation:**
- 🟢 None: No changes needed
- failure-handler can directly `delegate_task(skills=["dependency-resolver"])`

**Skill Impact:**
- None

**Workflow Impact:**
- None

**Risk:**
- None (already verified working)

---

### Decision 4: 代码修改安全（自动应用 patch + 阈值保护）

**Problem:** 自动修改代码可能引入新问题，无回滚机制

**Solution:**
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

**Implementation:**
- Add `apply_patch()` function in failure-handler
- Track `fix_attempts` count in manifest.json per test
- Add `max_retry_per_test: 3` in workflow.yaml

**manifest_schema.json Addition:**
```json
"fix_attempts": {
  "type": "integer",
  "description": "修复尝试次数",
  "default": 0,
  "minimum": 0
},
"fix_applied": true,
"fix_details": "...",
"fix_patch_file": {
  "type": ["string", "null"],
  "description": "patch 文件路径"
}
```

**Skill Impact:**
- `failure-handler/SKILL.md`: Add patch application logic
- `workflow.yaml`: Add `max_retry_per_test: 3` config

**Workflow Impact:**
- 🟡 Medium: Retry loop changes, but within failure-handler stage
- Threshold prevents infinite retries

**Risk:**
- 🟡 Medium: Patch application could break other tests
- Mitigation: Store original file hash for rollback detection

---

### Decision 5: Agent判断可靠性

**Problem:** LLM 可能误判错误类型

**Solution:** 保持现状，依赖"失败多次自动放弃"机制保护

**Reasoning:**
1. 失败后会重新分析（迭代修正）
2. 阈值保护防止无限尝试
3. 增加置信度评估会增加复杂度和成本

**Implementation:**
- 🟢 None: No changes needed
- Decision 4's threshold mechanism provides protection

**Skill Impact:**
- None

**Workflow Impact:**
- None

**Risk:**
- None (deferred to Decision 4)

---

### Decision 6: 超时控制（分批处理）【DEEP DIVE】

**Problem:** Stage 4 timeout=900s，但 50 个失败测试可能超时

**Solution (manifest-centric):**
- 每轮最多处理 N 个失败测试（如 10 个）
- 剩余失败测试保持 `failed` 状态，下一轮 batch-selector 自动选择
- **不使用 workflow_state 记录 deferred** — 完全基于 manifest 状态

**Implementation Complexity Analysis:**

| Component | Change Required | Complexity |
|-----------|-----------------|------------|
| workflow.yaml | Add `max_failed_per_iteration: 10` | Low |
| failure-handler | Slice failed_tests[:N] before processing | Low |
| batch-selector | Select from failed tests (retry queue) | Medium |

**Detailed Implementation:**

**6.1 workflow.yaml Addition:**
```yaml
stages:
  handle_failures:
    timeout: 900
    max_failed_per_iteration: 10  # NEW
```

**6.2 failure-handler Processing:**
```python
# 按阈值截取，不记录 remaining_failed
max_per_iteration = config.get("max_failed_per_iteration", 10)
failed_tests = failed_tests[:max_per_iteration]

# 剩余测试保持 failed 状态，下一轮 batch-selector 自动处理
# 无需额外记录，manifest-centric design
```

**6.3 batch-selector Behavior (manifest-centric):**
```python
# 从 manifest 读取所有状态（唯一数据源）
pending_tests = [t for t in manifest["tests"] if t["status"] == "pending"]
failed_tests = [t for t in manifest["tests"] if t["status"] == "failed"]
fixed_pending = [t for t in manifest["tests"] if t["status"] == "fixed_pending_verify"]

# 优先级队列（完全基于 manifest）
batch_tests = []
batch_tests.extend(fixed_pending[:batch_size])  # 验证批次优先

if len(batch_tests) < batch_size:
    slot = batch_size - len(batch_tests)
    batch_tests.extend(pending_tests[:slot])     # 新测试

if len(batch_tests) < batch_size:
    slot = batch_size - len(batch_tests)
    batch_tests.extend(failed_tests[:slot])      # 重试 failed tests

# batch_config 标记类型
batch_config = {
    "verification_tests": fixed_pending_subset,
    "new_tests": pending_subset,
    "retry_tests": failed_subset
}
```

**Critical Issue: State Coordination**

Decision 6 与 Decision 2 存在交叉：

| Scenario | D2 (fixed_pending_verify) | D6 (deferred_failed) |
|----------|---------------------------|----------------------|
| 修复后单测 passed | fixed_pending_verify | N/A |
| 修复后单测 failed | 保持 failed | 如果超出阈值 → deferred |
| 未处理（超时截取） | N/A | pending + failed 状态 |

**Recommended Approach:**
```
优先级排序：
1. fixed_pending_verify（验证批次优先）
2. failed tests（超时截取的 deferred）
3. pending tests（正常流程）

batch_config 结构：
{
  "verification_tests": [...],  # fixed_pending_verify
  "retry_tests": [...],         # failed tests from previous batch
  "new_tests": [...],           # pending tests
}
```

**Workflow Impact:**
- 🔴 **Medium-High**: Changes batch selection priority
- Loop iteration may process fewer new tests (more retry/verify tests)
- Timeout protection prevents runaway stages

**Risk Assessment:**
- 🟡 Medium: Interaction with Decision 2 needs careful design
- Edge case: If every batch has 50 failed tests, new tests never run

**Mitigation:**
```yaml
loop:
  max_failed_ratio_per_batch: 0.3  # 每批最多 30% 重试测试
  min_new_tests_per_batch: 20       # 每批至少 20 个新测试
```

---

### Decision 7: resource恢复机制

**Problem:** GPU OOM 可能是临时状态，标记 ignored 后永不重试

**Solution:** 保持 `ignored`，workflow 结束后汇总 resource 问题供用户处理

**Implementation:**
- Add resource summary generation in workflow complete stage
- Aggregate `ignored_reason` containing "CUDA", "OOM", "NCCL"

**Skill Impact:**
- `workflow/SKILL.md`: Add end-of-workflow resource summary
- `skills/ut/terminal-workflow/scripts/send_progress_card.py`: Add resource summary template

**Workflow Impact:**
- 🟢 Low: Only affects end-of-workflow reporting
- No changes to loop or state machine

**Risk:**
- 🟢 Low: Additive feature, no breaking changes

---

### Decision 8: ignored阈值

**Problem:** 多少 ignored 才算"完成"？

**Solution:** 在 GOAL.md 定义 ignored 阈值 ≤50%

**Implementation:**
- Update `tasks/ut/GOAL.md`:
```markdown
## Completion Criteria
- All tests processed (pending == 0)
- ignored_ratio <= 50% (宽松阈值，环境问题较多)
- Resource issues summarized for user review
```

**Skill Impact:**
- `GOAL.md` only

**Workflow Impact:**
- None (documentation only)

**Risk:**
- None

---

### Decision 9: errors[] + failures[] 双数组结构 + error_key 标准化【DEEP DIVE】

**Problem:**
1. 同一 batch 多个测试可能因同一原因失败
2. 一个 test 可能经历多次 errors 和多次 failures
3. pytest Error（无法执行）≠ Failure（断言失败），需区分
4. error_key 不标准化会导致统计分散

**Solution (方案 A - errors[] + failures[] 分开):**

**9.1 test 结构（双数组）：**
```json
{
  "test_node": "tests/test_load.py::test_llama",
  "status": "passed",
  "errors": [
    {
      "error_key": "transformers",
      "error_type": "dependency",
      "error_message": "ModuleNotFoundError: No module named 'transformers'",
      "status": "resolved",
      "occurred_at": "2026-06-12T14:00:00Z",
      "resolved_at": "2026-06-12T15:00:00Z"
    }
  ],
  "failures": [
    {
      "failure_key": "test_load:shape_mismatch",
      "failure_type": "assertion",
      "failure_message": "AssertionError: expected shape (1, 10) got (1, 5)",
      "status": "resolved",
      "occurred_at": "2026-06-12T15:30:00Z",
      "resolved_at": "2026-06-12T16:00:00Z",
      "fix_patch": "patches/shape_fix.patch"
    },
    {
      "failure_key": "test_load:value_tolerance",
      "failure_type": "assertion",
      "failure_message": "AssertionError: value exceeds tolerance 0.01",
      "status": "resolved",
      "occurred_at": "2026-06-12T16:30:00Z",
      "resolved_at": "2026-06-12T17:00:00Z",
      "fix_patch": "patches/tolerance_fix.patch"
    }
  ],
  "run_count": 4,
  "last_run_at": "2026-06-12T17:30:00Z"
}
```

**errors vs failures 定义：**
| 类型 | 含义 | pytest 状态 | error_type/failure_type |
|------|------|-------------|-------------------------|
| **Error** | 测试无法执行 | ERROR | dependency/version/download_error/network/resource |
| **Failure** | 断言失败 | FAILED | assertion |

**9.2 error_key 标准化规则：**

| error_type | error_key 格式 | 示例 | 提取方式 |
|------------|----------------|------|----------|
| dependency | `{package}` | `transformers` | 规则自动提取 |
| download_error | `{org}/{model}` | `meta-llama/Llama-3.2-1B` | 规则自动提取 |
| version | `{module}.{function}.{change}` | `torch.softmax.dim_arg` | 规则自动提取 |
| network | `{host}:{error}` | `huggingface.co:timeout` | 规则自动提取 |
| resource | `{resource_type}` | `cuda_oom` | 规则自动提取 |

**9.3 failure_key 标准化规则：**

| failure_type | failure_key 格式 | 示例 | 提取方式 |
|--------------|------------------|------|----------|
| assertion | `{test_file}:{bug_type}` | `test_load:shape_mismatch` | LLM生成+校验 |

**9.4 自动提取函数（failure-handler）：**
```python
def normalize_error_key(error_type, error_message):
    """从原始错误信息提取标准化 error_key"""
    
    if error_type == "dependency":
        match = re.search(r"No module named '(\w+)'", error_message)
        return match.group(1).lower() if match else None
    
    if error_type == "download_error":
        match = re.search(r"download ([\w\-]+/[\w\-\.]+)", error_message)
        return match.group(1) if match else None
    
    if error_type == "version":
        return extract_api_change_key(error_message)
    
    if error_type == "network":
        match = re.search(r"(?:timeout|connection).*?(\w+\.\w+)", error_message)
        return match.group(1).lower() if match else "network_unknown"
    
    if error_type == "resource":
        if "CUDA out of memory" in error_message:
            return "cuda_oom"
        if "NCCL" in error_message:
            return "nccl_error"
        return "resource_unknown"

def normalize_failure_key(failure_message, test_file):
    """LLM 生成 failure_key，需格式校验"""
    # 格式: {test_file}:{bug_type}
    # LLM prompt 提供格式要求和示例
    ...
```

**9.5 resolved_errors + resolved_failures（聚合索引）：**
```json
{
  "resolved_errors": {
    "transformers": {
      "type": "dependency",
      "resolved_at": "2026-06-12T15:00:00Z"
    }
  },
  "resolved_failures": {
    "test_load:shape_mismatch": {
      "type": "assertion",
      "resolved_at": "2026-06-12T16:00:00Z",
      "fix_patch": "patches/shape_fix.patch"
    }
  }
}
```

**9.6 affected 统计（按需聚合）：**
```python
# 统计某 error_key 影响的测试数
affected_by_error = len([
    t for t in manifest["tests"]
    if any(e.get("error_key") == "transformers" for e in t.get("errors", []))
])

# 统计某 failure_key 影响的测试数
affected_by_failure = len([
    t for t in manifest["tests"]
    if any(f.get("failure_key") == "test_load:shape_mismatch" for f in t.get("failures", []))
])
```

**9.7 statistics 分开统计：**
```json
"statistics": {
  "total": 13000,
  "passed": 500,
  "failed": 50,      // 当前 status=failed 的测试数
  "error": 16,       // 当前 status=error 的测试数
  "ignored": 10,
  "pending": 12434,
  
  // 可按需聚合（不存储）
  // errors_count: 从 errors[] 统计
  // failures_count: 从 failures[] 统计
}
```

**Skill Impact:**
- `manifest_schema.json`: Add `errors[]`, `failures[]`, `resolved_errors`, `resolved_failures`
- `failure-handler/SKILL.md`: 
  - Split logic: error handling vs failure handling
  - Add `normalize_error_key()` + `normalize_failure_key()`
- `manifest-updater/SKILL.md`: 
  - Update errors[].status / failures[].status
  - Update resolved_errors / resolved_failures

**Workflow Impact:**
- 🟡 Medium: Two arrays but clearer separation
- failure-handler 逻辑分离：errors（环境）→ failures（代码）

**Risk:**
- 🟡 Medium: failure_key LLM 生成一致性
- Mitigation: 格式校验 + 历史匹配 + 规则优先

---

### Decision 10: 状态一致性（单一数据源）【DEEP DIVE】

**Problem:** manifest.json 和 workflow_state.json 的 stats 可能不一致

**Solution:** 单一数据源 —— workflow_state.json 的 stats 直接从 manifest.json 读取

**Implementation Complexity Analysis:**

| Component | Current Behavior | New Behavior |
|-----------|------------------|--------------|
| workflow_state.json | Stores `stats` independently | No `stats` field, read from manifest |
| workflow skill | Calculates stats from state | Read `manifest["statistics"]` |
| init_workflow_state.py | Initializes stats | Don't initialize stats in state |
| All stats readers | Read from workflow_state | Read from manifest |

**Current State (Problem):**
```json
// workflow_state.json
{
  "stats": {
    "passed": 500,
    "failed": 50,  // ← 可能与 manifest 不同步
    "ignored": 16
  }
}

// manifest.json
{
  "statistics": {
    "passed": 505,  // ← manifest-updater 更新了
    "failed": 48,
    "ignored": 15
  }
}
```

**New State (Solution):**
```python
# workflow_state.json 不存储 stats 或 resolved_failures_errors
# 所有协调数据都在 manifest.json（单一数据源）

# workflow skill 每次需要统计时：
def get_current_stats(workflow_state_path):
    paths = get_paths(workflow_state_path)
    manifest = json.loads(Path(paths["manifest"]).read_text())
    return manifest["statistics"]

# workflow_state.json 最终只存储：
{
  "current_stage": "select_batch",
  "iteration": 5,
  "current_batch_id": "batch_20260612_143000",
  "break_signals": {...}
  # 不包含: stats, resolved_failures_errors
}
```

**manifest.json 协调数据结构：**
```json
{
  "tests": [...],           // 测试状态（唯一数据源）
  "statistics": {...},      // 统计计数（唯一数据源）
  "resolved_failures_errors": {...}  // 已解决问题（唯一数据源）
}
```

**Cross-Skill Coordination via manifest:**
- batch-selector: 读取 `tests` 状态选择批次
- failure-handler: 读取 `resolved_failures_errors` 缓存
- manifest-updater: 更新 `tests` 状态 + `resolved_failures_errors`
- workflow: 读取 `statistics` 显示进度

**无额外依赖：**
- workflow_state 只存运行时临时状态
- 所有持久化数据在 manifest.json

**Detailed Implementation:**

**10.1 init_workflow_state.py Changes:**
```python
# 当前：初始化 stats
state["stats"] = {
    "total": len(manifest["tests"]),
    "pending": len(manifest["tests"]),
    ...
}

# 新：不初始化 stats，只存储 metadata
state = {
    "current_stage": "collect",
    "iteration": 0,
    "config": {...},
    "paths": {...},
    # 不包含 stats
}
```

**10.2 workflow skill Changes:**
```python
# 当前：从 state 读取 stats
stats = state["stats"]
pending_count = stats["pending"]

# 新：从 manifest 读取 stats
manifest = json.loads(Path(state["paths"]["manifest"]).read_text())
stats = manifest["statistics"]
pending_count = stats["pending"]
```

**10.3 All Skills Reading Stats:**
- `batch-selector`: Read `manifest["statistics"]["pending"]`
- `workflow`: Read `manifest["statistics"]` for progress card
- `send_progress_card.py`: Read manifest directly

**Skill Impact:**
- 🔴 **High**: All 6 skills that read stats need modification
  - workflow
  - batch-selector
  - failure-handler
  - manifest-updater
  - ut-test-collector
  - send_progress_card.py

**Workflow Impact:**
- 🔴 **High**: Fundamental change in state management
- Benefits: Consistency guaranteed, no drift
- Drawbacks: More file reads (manifest.json is larger)

**Risk Assessment:**
- 🟡 **Medium-High Risk Factors:**
  1. **Breaking change**: All stats readers need update
  2. **Performance**: Reading manifest every iteration (manifest can be 10MB+)
  3. **Edge case**: What if manifest is corrupted? Need fallback

**Mitigation Strategies:**
1. Add `get_stats_from_manifest()` helper in `shared/config_loader.py`
2. Cache manifest read for 1 iteration (invalidate after manifest-updater)
3. Add schema validation before using manifest stats

**Recommended Implementation Order:**
```
Phase 1: Add shared helper
  - shared/stats_reader.py: get_stats_from_manifest()

Phase 2: Update all skills one-by-one
  - workflow → batch-selector → failure-handler → others

Phase 3: Remove stats from workflow_state.json
  - init_workflow_state.py update
  - Clean up existing workflow_state files
```

---

## Section 3: Prioritized Action Plan

### Phase 1: Zero-Risk Foundations (Easy)

**Week 1 - Documentation & Verification**

| Decision | Action | Effort |
|:--------:|--------|:------:|
| D3 | Verify dependency-resolver scripts work | 1h |
| D5 | Document threshold mechanism (no code) | 0h |
| D8 | Update GOAL.md with ignored threshold | 0.5h |
| D7 | Add resource summary template | 2h |

**Deliverables:**
- Updated `tasks/ut/GOAL.md`
- Verified `dependency-resolver` integration
- Resource summary script in `send_progress_card.py`

---

### Phase 2: Single-Skill Changes (Medium)

**Week 2 - failure-handler Enhancements**

| Decision | Action | Effort |
|:--------:|--------|:------:|
| D1 | Add two-stage classification | 4h |
| D4 | Add patch application + threshold | 6h |
| D9 | Add dependency cache in workflow_state | 3h |

**Deliverables:**
- Updated `failure-handler/SKILL.md` (v3.0)
- `workflow.yaml` with `max_retry_per_test: 3`
- `manifest_schema.json` with `resolved_failures_errors` field

---

### Phase 3: Cross-Skill Coordination (High)

**Week 3-4 - batch-selector + manifest Changes**

| Decision | Action | Effort | Dependencies |
|:--------:|--------|:------:|--------------|
| D2 | Add `fixed_pending_verify` status | 8h | D4 (patch logic) |
| D6 | Add `max_failed_per_iteration` | 4h | D2 (priority queue) |
| D10 | Single source stats | 6h | D2 (manifest-updater changes) |

**Implementation Sequence:**

```
Step 1: manifest_schema.json
  - Add fixed_pending_verify enum
  - Add fix_attempts, fix_verified fields

Step 2: shared/stats_reader.py
  - Helper for reading manifest statistics
  - Schema validation

Step 3: batch-selector/SKILL.md
  - Filter pending + fixed_pending_verify
  - Priority queue logic

Step 4: manifest-updater/SKILL.md
  - Handle fixed_pending_verify → passed/failed
  - Handle verification batch results

Step 5: workflow/SKILL.md
  - Use stats_reader helper
  - Handle partial processed batches (D6)

Step 6: workflow.yaml
  - Add max_failed_per_iteration: 10
  - Add max_retry_per_test: 3

Step 7: failure-handler/SKILL.md
  - Write fixed_pending_verify status
  - Slice failed_tests[:max_per_iteration]
```

**Deliverables:**
- `manifest_schema.json` v2.1
- Updated `batch-selector/SKILL.md` v3.0
- Updated `manifest-updater/SKILL.md` v4.0
- Updated `workflow/SKILL.md` v6.0
- Updated `workflow.yaml` v2.3

---

### Risk Mitigation Checklist

| Risk | Mitigation | Phase |
|------|------------|:-----:|
| D2 state machine | Limit fixed_pending_verify per batch | 3 |
| D2 stuck tests | Timeout after 2 iterations → back to failed | 3 |
| D4 patch breaking | Store original file hash | 2 |
| D6 interaction with D2 | Priority queue + ratio limits | 3 |
| D10 breaking all readers | Shared helper + phased rollout | 3 |
| D10 performance | Cache manifest read for 1 iteration | 3 |

---

## Cross-Skill Impact Matrix

```
                D1  D2  D3  D4  D5  D6  D7  D8  D9  D10
workflow         -   ●   -   ○   -   ●   ●   -   -   ●
batch-selector   -   ●   -   -   -   ●   -   -   -   ●
failure-handler  ●   ●   -   ●   -   ●   -   -   ●   ●
manifest-updater -   ●   -   -   -   -   -   -   ●   -
dependency-res.  -   -   -   -   -   -   -   -   -   -
ut-test-collect. -   -   -   -   -   -   -   -   -   ●
workflow.yaml    -   ○   -   ○   -   ○   -   -   -   -
manifest_schema  -   ●   -   ○   -   -   -   -   ●   -
GOAL.md          -   -   -   -   -   -   -   ●   -   -

● = Major change (flow/logic)
○ = Minor change (config/doc)
- = No change

Key Changes:
- D9: manifest_schema 新增 resolved_failures_errors
- D6: batch-selector 从 manifest.failed 选择重试队列
- D10: workflow_state 只存运行时状态，不存协调数据
```

---

## Recommendations Summary

**Must Implement (High Impact):**
- D2, D6, D10 — Cross-skill coordination required

**Should Implement (Medium Impact):**
- D1, D4, D9 — Single skill but significant logic change

**Can Defer (Low Impact):**
- D3, D5, D7, D8 — Verification/documentation only

**Estimated Total Effort:**
- Phase 1: 3.5 hours
- Phase 2: 13 hours
- Phase 3: 18 hours
- **Total: ~34.5 hours (4-5 days)**

---

## Related Documents

- [Design Doc](./2026-06-12-failure-handler-review-design.md) — Original 10 decisions
- [failure-handler/SKILL.md](../../skills/ut/failure-handler/SKILL.md) — Current implementation (v2.1)
- [workflow/SKILL.md](../../skills/ut/terminal-workflow/SKILL.md) — Supervisor orchestration
- [workflow.yaml](../../.agents/workflow.yaml) — Configuration file

---

*Created: 2026-06-12*
*Updated: 2026-06-13*
*Version: 1.2.0*

---

## Appendix A: Manifest-Centric Coordination Principle

**核心原则：manifest.json 是唯一协调数据源**

| 数据类型 | 存储位置 | 用途 |
|----------|----------|------|
| tests 状态 | manifest.json | batch-selector 选择批次 |
| statistics | manifest.json | workflow 显示进度 |
| errors[] / failures[] | manifest.json | failure-handler 追踪历史 |
| resolved_errors / resolved_failures | manifest.json | failure-handler 缓存索引 |

**workflow_state.json 只存运行时临时状态：**
```json
{
  "current_stage": "...",
  "iteration": 5,
  "current_batch_id": "...",
  "break_signals": {...}
}
```

**无额外依赖：**
- 不使用 workflow_state 存储协调数据
- 不引入额外的状态文件
- 所有 skill 通过 manifest 协调

---

## Appendix B: Script-First, Agent-Judgment Principle

**核心原则：确定性处理交给脚本，逻辑判断交给 Agent**

| 层级 | 处理方式 | 适用场景 | 示例 |
|------|----------|----------|------|
| L1 脚本规则 | 关键词匹配、正则提取 | 确定性高、规则清晰 | error_type 分类、error_key 标准化 |
| L2 脚本调用 | 调用已有脚本 | 固定流程 | dependency-resolver、重试、GPU检测 |
| L3 脚本定位 | traceback 解析、grep | 可规则提取 | 定位代码文件、提取上下文 |
| L4 脚本统计 | 聚合计算 | 数学运算 | affected_tests、statistics 计算 |
| L5 Agent 判断 | LLM 语义理解 | 需理解上下文 | 判断 test/vllm 问题来源 |
| L6 Agent 生成 | LLM 代码修复 | 需代码理解 | 生成 patch、修复逻辑 |

**failure-handler 分工示例：**

```python
# L1-L4: 脚本处理
error_type = classify_error_by_keywords(error_message)      # 脚本
error_key = normalize_error_key(error_type, error_message)  # 脚本
traceback_info = parse_traceback(error_message)             # 脚本
code_location = locate_code_from_traceback(traceback_info)  # 脚本
code_context = read_remote_file(code_location)              # 脚本
affected_tests = count_affected_tests(error_key)            # 脚本统计

# L5-L6: Agent 处理
fix_patch = agent_analyze_and_fix(error_message, code_context)  # Agent LLM
```

**优势：**
- 脚本部分：可靠性高、速度快、成本低、可复用
- Agent 部分：处理真正需要理解的复杂场景

**SKILL 文档要求：**
- 明确说明脚本 vs Agent 的边界
- 脚本部分提供具体函数名和参数
- Agent 部分提供 prompt 示例和输出格式
- 所有 skill 通过 manifest 协调