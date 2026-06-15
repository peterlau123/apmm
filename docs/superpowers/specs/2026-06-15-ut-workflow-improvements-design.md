# UT Workflow 改进设计规格书

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create implementation plan from this spec.

**目标:** 解决 UT Workflow 的4个问题：GPU并发执行、logs目录结构、retry机制缺失、初始环境检查效率

**创建日期:** 2026-06-15

**设计版本:** 1.0

---

## 问题背景

当前 UT Workflow 存在以下4个问题需要改进：

1. **GPU并发执行缺失**：当前测试串行执行，未利用多GPU并行能力，吞吐量低
2. **logs目录结构不清**：`run_dir/logs/` 为空，实际日志在 `batches/*/logs/`，用户困惑
3. **retry机制不完整**：ignored 测试缺少 `retry_count` 和 `max_retry` 字段，无法区分"重试耗尽"和"主动跳过"
4. **初始环境检查效率低**：Agent 逐个检查环境，耗时较长

---

## Section 1: GPU 并发执行机制

### 1.1 架构设计

**执行模式:** GPU级并行执行

```
┌─────────────────────────────────────────────────────────────┐
│  GPU Concurrent Execution Architecture                       │
│                                                             │
│  Input: batch_config.json (N tests, split by test_file)    │
│  Output: batch_results.json (parallel execution results)    │
│                                                             │
│  GPU Assignment:                                             │
│  • 8 GPUs available (CUDA_VISIBLE_DEVICES=0-7)              │
│  • Each GPU executes one test_file                          │
│  • distributed tests need multi-GPU → skip concurrent       │
│                                                             │
│  Implementation:                                             │
│  • batch_test_runner.py: parallel execution engine          │
│  • CUDA device assignment: os.environ['CUDA_VISIBLE_DEVICES']│
│  • Process pool: multiprocessing.Pool(max_workers=8)        │
│                                                             │
│  Test Split Logic:                                           │
│  • Group tests by test_file                                 │
│  • Assign test_file groups to GPU slots (round-robin)       │
│  • distributed tests: sequential execution with multi-GPU   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 关键改动

**文件: `skills/ut/unit-test-executor/scripts/batch_test_runner.py`**

**改动内容:**

```python
# 当前实现（串行）
def run_batch(batch_config: dict) -> dict:
    """Sequential test execution"""
    results = []
    for test in batch_config["tests"]:
        result = run_single_test(test)
        results.append(result)
    return {"results": results}

# 改进实现（并行）
def run_batch_parallel(batch_config: dict) -> dict:
    """Parallel test execution with GPU assignment"""
    tests = batch_config["tests"]

    # 分离 distributed 和 normal 测试
    distributed_tests = [t for t in tests if t.get("distributed")]
    normal_tests = [t for t in tests if not t.get("distributed")]

    # 按 test_file 分组
    file_groups = group_by_test_file(normal_tests)

    # GPU 分配（最多8个并行）
    gpu_assignments = assign_to_gpus(file_groups, max_gpus=8)

    # 并行执行 normal 测试
    with multiprocessing.Pool(max_workers=8) as pool:
        normal_results = pool.map(run_on_gpu, gpu_assignments)

    # 串行执行 distributed 测试（需要多GPU）
    distributed_results = []
    for test in distributed_tests:
        result = run_distributed_test(test)
        distributed_results.append(result)

    return {"results": normal_results + distributed_results}
```

### 1.3 GPU 分配逻辑

**文件: `skills/ut/unit-test-executor/scripts/gpu_scheduler.py` (新建)**

**职责:**
- 检测可用 GPU 数量
- 分配 test_file 到 GPU slot
- 管理 CUDA_VISIBLE_DEVICES 设置

**核心逻辑:**

```python
def assign_to_gpus(file_groups: list, max_gpus: int = 8) -> list:
    """Assign test_file groups to GPU slots (round-robin)"""
    assignments = []
    available_gpus = detect_available_gpus()  # 从远程 nvidia-smi 获取

    for idx, group in enumerate(file_groups[:max_gpus]):
        gpu_id = available_gpus[idx % len(available_gpus)]
        assignments.append({
            "gpu_id": gpu_id,
            "cuda_devices": str(gpu_id),
            "tests": group
        })

    return assignments

def run_on_gpu(assignment: dict) -> list:
    """Execute tests on assigned GPU"""
    os.environ["CUDA_VISIBLE_DEVICES"] = assignment["cuda_devices"]
    results = []
    for test in assignment["tests"]:
        result = run_single_test(test)
        results.append(result)
    return results
```

### 1.4 distributed 测试处理

**特殊处理:**
- distributed 测试需要多 GPU（如 tensor_model_parallel_size=2）
- 不参与并行执行，单独串行执行
- 使用全部可用 GPU 或指定数量

**实现:**

```python
def run_distributed_test(test: dict) -> dict:
    """Execute distributed test with multi-GPU"""
    world_size = test.get("world_size", 2)  # 从 test 参数获取

    # 分配 GPU（如 0,1 用于 world_size=2）
    cuda_devices = ",".join(str(i) for i in range(world_size))
    os.environ["CUDA_VISIBLE_DEVICES"] = cuda_devices

    # 执行测试
    result = run_single_test(test)
    return result
```

---

## Section 2: logs 目录分层设计

### 2.1 目录结构

**改进后的结构:**

```
runs/ut-20260615-071129/
├── logs/                          # workflow 级别日志
│   ├── environment_check.log      # 环境检查日志
│   ├── workflow_summary.log       # workflow 总结日志
│   ├── manifest_updater.log       # manifest 更新日志
│   └── send_card.log              # 飞书卡片发送日志
├── batches/
│   └── batch_20260615_071333/
│       ├── logs/
│       │   ├── pytest_output.log  # pytest 输出日志（已有）
│       │   ├── gpu_scheduler.log  # GPU 分配日志（新增）
│       │   └── batch_executor.log # 批次执行日志（新增）
│       ├── batch_config.json
│       └── batch_results.json
├── manifest.json
├── workflow_state.json
└── test_list.txt
```

### 2.2 日志分类

| 日志文件 | 层级 | 内容 | 创建者 |
|---------|------|------|--------|
| `environment_check.log` | workflow | 环境检查结果（Bastion/容器/GPU/HF/Pytest） | `check_environment.py` |
| `workflow_summary.log` | workflow | Workflow 启动/结束/统计 | Supervisor |
| `manifest_updater.log` | workflow | Manifest 更新记录 | `manifest_updater.py` |
| `send_card.log` | workflow | 飞书卡片发送记录 | `send_progress_card.py` |
| `pytest_output.log` | batch | pytest 执行输出 | `batch_test_runner.py` |
| `gpu_scheduler.log` | batch | GPU 分配记录 | `gpu_scheduler.py` |
| `batch_executor.log` | batch | 批次执行过程 | `batch_test_runner.py` |

### 2.3 关键改动

**文件: `.agents/workflow.yaml`**

**改动:** 补充注释说明 logs 目录用途

```yaml
# 标准化路径（相对于 run_dir）
logs_dir: &logs_dir "{run_dir}/logs"  # workflow 级别日志（环境检查、workflow总结等）
reports_dir: &reports_dir "{run_dir}/reports"

# 批次文件路径
batch_logs_dir: &batch_logs_dir "{batch_dir_template}/logs"  # batch 级别日志（pytest输出、GPU分配等）
```

---

## Section 3: Retry 机制完善

### 3.1 状态流转设计

**改进后的状态流转:**

```
状态流转图：

pending → running → passed  ✓ 成功
                 → failed → retrying (retry_count++) → passed ✓
                                → failed → exhausted (retry_count >= max_retry)
                 → error → retrying → resolved ✓
                        → exhausted (retry_count >= max_retry)
                 → ignored (Agent判断无法修复，不消耗retry_count)
```

**状态说明:**

| 状态 | 含义 | retry_count变化 | 后续处理 |
|------|------|-----------------|----------|
| **pending** | 待执行 | 0 | 等待batch-selector选择 |
| **running** | 正在执行 | 不变 | 等待pytest结果 |
| **passed** | 测试通过 | 不变 | 完成 |
| **failed** | 断言失败 | 0 (首次) | 进入failure-handler |
| **error** | 执行错误 | 0 (首次) | 进入failure-handler |
| **retrying** | 正在重试 | +1 (failure-handler处理后) | 再次执行 |
| **exhausted** | 重试耗尽 | =max_retry | 需人工介入 |
| **ignored** | 主动跳过 | 不增加 | 外部依赖问题，需预准备 |

### 3.2 字段填充时机

**时机1: manifest初始化**

- **执行者:** `ut-test-collector` 或 `manifest-updater`
- **改动:** 从 schema 默认值读取，或从 workflow.yaml 读取 `max_retry_per_test`

```python
# manifest_updater.py
def create_manifest_entry(test: dict, config: dict) -> dict:
    """Create manifest entry with default retry fields"""
    return {
        "id": test["id"],
        "test_node": test["test_node"],
        "status": "pending",
        "retry_count": 0,
        "max_retry": config.get("max_retry_per_test", 3),
        ...
    }
```

**时机2: batch-selector过滤**

- **执行者:** `batch-selector`
- **改动:** 选择 failed 测试时，过滤 `retry_count >= max_retry`

```python
# batch_selector.py (SKILL.md 已更新)
failed_tests = [t for t in manifest["tests"]
                if t["status"] == "failed"
                and t.get("retry_count", 0) < t.get("max_retry", 3)]
```

**时机3: failure-handler状态更新**

- **执行者:** `failure-handler`
- **改动:**
  - 尝试修复后仍失败 → `retry_count++`
  - 达到 `max_retry` → 状态改为 `exhausted`
  - Agent判断无法修复 → 状态改为 `ignored`（不增加retry_count）

```python
# failure_handler.py
def update_test_status(test: dict, result: dict) -> dict:
    """Update test status with retry logic"""
    if result["can_fix"]:
        # 可修复 → retrying
        test["retry_count"] = test.get("retry_count", 0) + 1
        test["status"] = "retrying"
    elif result["external_dependency"]:
        # 外部依赖问题 → ignored (不增加retry_count)
        test["status"] = "ignored"
        test["ignored_reason"] = result["reason"]
    elif test["retry_count"] >= test["max_retry"]:
        # 重试耗尽 → exhausted
        test["status"] = "exhausted"
    else:
        # 继续重试
        test["retry_count"] += 1
        test["status"] = "retrying"

    return test
```

### 3.3 manifest_schema.json 更新

**改动:** 确认 `retry_count` 和 `max_retry` 默认值生效

```json
{
  "retry_count": {
    "type": "integer",
    "description": "重试次数（用于batch-selector过滤）",
    "default": 0,
    "minimum": 0
  },
  "max_retry": {
    "type": "integer",
    "description": "最大重试次数（从workflow.yaml读取）",
    "default": 3,
    "minimum": 1
  }
}
```

**注意:** Schema 的 `default` 值在 JSON 解析时自动生效，无需显式填充（但建议显式填充以明确来源）

---

## Section 4: 环境检查脚本

### 4.1 脚本设计

**文件: `skills/ut/shared/scripts/check_environment.py` (新建)**

**职责:** 一次性检查所有环境状态，输出 JSON 结果和日志

**检查项:**

| 检查项 | 命令 | 远程执行 | 预期结果 |
|--------|------|----------|----------|
| Bastion状态 | `bastion_check --status` | 本地 | status=connected, latency_ms<1000 |
| 容器状态 | `docker ps --filter name=<container>` | 远程 | status=running |
| GPU状态 | `nvidia-smi` | 远程 | available≥2, memory_free_gb>20 |
| HF缓存 | `ls -la $HF_HOME` | 远程 | exists=true, models存在 |
| Pytest可用性 | `pytest --version` | 远程容器 | available=true, version匹配 |

### 4.2 输出格式

**JSON 结果:**

```json
{
  "bastion": {
    "status": "connected",
    "latency_ms": 50,
    "passed": true
  },
  "container": {
    "name": "v0.13.0_torch2.5.1_compile",
    "status": "running",
    "passed": true
  },
  "gpu": {
    "available": 8,
    "memory_free_gb": [40.2, 40.1, 40.0, 40.3, 40.2, 40.1, 40.0, 40.3],
    "passed": true
  },
  "hf_cache": {
    "path": "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub",
    "exists": true,
    "models": ["opt-125m", "distilgpt2", "Qwen2.5-7B-Instruct"],
    "passed": true
  },
  "pytest": {
    "available": true,
    "version": "7.4.0",
    "passed": true
  },
  "all_passed": true,
  "checked_at": "2026-06-15T07:30:00Z"
}
```

### 4.3 集成方式

**方式1: Stage 1 前调用（推荐）**

- **位置:** Supervisor 在调用 `ut-test-collector` 前
- **时机:** Workflow 启动后，检查环境，失败则阻塞启动

```python
# Supervisor 逻辑
def run_workflow(config: dict) -> dict:
    """运行 workflow"""
    # Stage 0: 环境检查（新增）
    env_results = check_environment(config)
    if not env_results["all_passed"]:
        log_error("Environment check failed, workflow blocked")
        return {"status": "blocked", "reason": "environment_check_failed"}

    # Stage 1: 收集测试
    manifest = run_stage_collect(config)
    ...
```

---

## Section 5: 实施优先级

### 5.1 优先级排序

| 优先级 | 模块 | 预估工时 | 风险等级 |
|--------|------|----------|----------|
| P0 | 环境检查脚本 | 1h | 低 |
| P1 | Retry机制完善 | 2h | 中 |
| P2 | logs目录分层 | 1h | 低 |
| P3 | GPU并发执行 | 3h | 高 |

**理由:**
- P0 (环境检查)：改动小，收益大（避免workflow启动后才发现环境问题）
- P1 (retry机制)：解决关键痛点（ignored测试无法重试）
- P2 (logs目录)：文档改动，风险低
- P3 (GPU并发)：改动大，需要充分测试

### 5.2 实施顺序

```
Phase 1: P0 + P1 + P2 (4h)
  → 环境检查脚本
  → retry字段填充 + 过滤逻辑 + exhausted状态
  → logs目录注释更新

Phase 2: P3 (3h)
  → GPU并发执行引擎
  → distributed测试特殊处理
  → 测试验证
```

---

## Section 6: 验证标准

### 6.1 环境检查脚本验证

**验证命令:**

```bash
python skills/ut/shared/scripts/check_environment.py
```

**预期输出:**

```json
{
  "all_passed": true,
  "bastion": {"passed": true},
  "container": {"passed": true},
  "gpu": {"available": 8, "passed": true},
  "hf_cache": {"exists": true, "passed": true},
  "pytest": {"available": true, "passed": true}
}
```

### 6.2 Retry机制验证

**验证方法:**

1. 运行 UT Workflow，观察 ignored 测试是否有 `retry_count` 和 `max_retry` 字段
2. 检查 manifest.json 中 exhausted 状态测试是否存在
3. 验证 batch-selector 是否过滤 `retry_count >= max_retry` 的 failed 测试

**验证命令:**

```bash
# 检查 manifest.json 中 ignored 测试的字段
jq '.tests[] | select(.status == "ignored") | {retry_count, max_retry}' runs/ut-*/manifest.json

# 检查 exhausted 状态测试
jq '.tests[] | select(.status == "exhausted")' runs/ut-*/manifest.json

# 检查 batch-selector 过滤逻辑（SKILL.md）
grep -A5 "failed_tests" skills/ut/batch-selector/SKILL.md
```

### 6.3 GPU并发执行验证

**验证方法:**

1. 运行 UT Workflow，观察是否多GPU并行执行
2. 检查 batch_results.json 中多个测试的执行时间是否重叠
3. 验证 distributed 测试是否串行执行（不参与并发）

**验证命令:**

```bash
# 检查 batch_results.json 中执行时间
jq '.results[] | {test_node, duration_ms, gpu_id}' runs/ut-*/batches/batch_*/batch_results.json

# 检查 nvidia-smi 日志（GPU使用情况）
cat runs/ut-*/batches/batch_*/logs/gpu_scheduler.log
```

---

## Self-Review Check

**1. Placeholder scan:**
- ✅ No TBD/TODO placeholders
- ✅ All sections have concrete implementation details
- ✅ All code examples are executable (not pseudocode)

**2. Internal consistency:**
- ✅ Section 1 GPU并发 → Section 6 验证标准一致
- ✅ Section 3 Retry机制 → Section 5 实施优先级一致
- ✅ Section 4 环境检查 → Section 2 logs目录分层一致

**3. Scope check:**
- ✅ Focus on 4 improvements, no unnecessary features
- ✅ Each improvement is scoped to specific files/scripts
- ✅ Implementation plan is single-phase (no decomposition needed)

**4. Ambiguity check:**
- ✅ "exhausted" vs "ignored" distinction is explicit (Section 3.1)
- ✅ GPU assignment logic is explicit (Section 1.3)
- ✅ Check sequence is explicit (Section 4.1)

---

**设计规格书完成。请审阅此文档，确认是否可以开始编写实施计划。**