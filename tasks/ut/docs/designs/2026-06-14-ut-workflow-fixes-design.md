# UT Workflow 问题修复设计文档

**日期**: 2026-06-14
**方案**: 方案 A（最小修复）
**状态**: 已批准
**注意：** `.agents/workflow.yaml`已废弃（2026-06-29），配置机制已迁移至`tasks/ut/deployment/production/config/`模板库 + `runs/ut-{timestamp}/`副本机制。

---

## 问题概述

UT Workflow 执行过程中发现3个问题：

1. **飞书卡片通过率显示 0.0%**（实际应为 33.33%）
2. **workflow.yaml execution 配置未被代码使用**（冗余配置）
3. **workflow.yaml 配置顺序需调整**（kanban 和 notifications 应放到 worker_output_schema 后面）
4. **环境配置信息分散**（t_ascend、HF mirror、依赖路径等）

---

## 方案对比

| 方案 | 修复范围 | 工作量 | 推荐度 |
|------|----------|--------|--------|
| **A - 最小修复** | 修复已知问题，删除冗余配置 | 小 | ⭐⭐⭐⭐⭐ |
| B - 系统性优化 | A + Agent 自动加载环境知识 | 中 | ⭐⭐⭐ |
| C - 架构级改造 | 实现多 agent 架构 | 大 | ❌ |

**选择**: 方案 A（最小修复）

---

## 设计细节

### Section 1: 飞书卡片通过率计算修复

**问题根因**：
- `send_progress_card.py:63` 从 manifest.statistics 读取 `pass_rate`
- manifest.json 未写入 `pass_rate` 字段，导致默认值为 0

**修改位置**: `skills/ut/terminal-workflow/scripts/send_progress_card.py:63-64`

**修改内容**:

```python
# 当前代码（错误）
pass_rate = stats.get("pass_rate", 0)

# 修改为（正确）
pass_rate = (passed / executed * 100) if executed > 0 else 0.0
```

**计算逻辑**:
- `executed = passed + failed + error + ignored`（不含 pending）
- `pass_rate = passed / executed * 100`
- 如果 `executed == 0`，返回 `0.0`（避免除零）

**影响范围**:
- 所有飞书卡片（progress、complete、alert 等）都会显示正确的通过率
- 不影响其他功能

---

### Section 2: 删除未使用的 execution 配置

**问题根因**:
- `workflow.yaml` 的 `execution` 配置未被代码使用
- `supervisor_loop.py` 已废弃（标注"v5.0 后主循环逻辑移至 SKILL.md 内联执行"）
- 当前 workflow 是单 agent 内联执行，不需要多 agent 协作配置

**删除位置**: `.agents/workflow.yaml:execution` 配置块

**删除内容**:

```yaml
# ============================================================
# Execution Config - 执行配置
# ============================================================
execution:
  supervisor:
    max_context_tokens: 10000
    reload_state_interval: 1
    cleanup_history: true

  worker:
    timeout_per_stage: 600
    max_retries: 3
    delegate_task_toolsets:
      - terminal
      - file
      - web
```

**删除影响**:
- ✅ 无影响（代码未使用）
- ✅ 减少 workflow.yaml 的复杂度

---

### Section 3: 调整 workflow.yaml 配置顺序

**问题根因**:
- `kanban` 和 `notifications` 配置位置不符合逻辑分组

**调整位置**: `.agents/workflow.yaml`

**当前顺序**:
```
worker_output_schema → notifications → kanban → execution
```

**调整后顺序**:
```
worker_output_schema → kanban → notifications
```

**调整逻辑**:
- 配置分组清晰：
  1. workflow（元信息）
  2. config（路径和环境）
  3. input_filter（输入处理）
  4. stages（执行阶段）
  5. loop（循环配置）
  6. worker_output_schema（输出格式）
  7. kanban 和 notifications（通知和协作）

---

### Section 4: 补充环境配置说明

**问题根因**:
- t_ascend、HF mirror、依赖下载路径等信息分散在多个文档
- Agent 执行 workflow 时不会自动加载 dependency-resolver 等文档

**补充位置**: `.agents/workflow.yaml` 的 `config.container_env` 注释

**当前注释**:
```yaml
# 容器环境变量（一次设置，所有测试生效）
# 来源: tasks/ut/scripts/hf_env.sh - HuggingFace 离线环境配置
# 说明: 远程服务器 t_h20 无外网访问，需使用预下载的本地模型缓存
# 缓存位置: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/
# 已有模型: opt-125m, distilgpt2, Qwen系列等
```

**补充注释**（新增）:
```yaml
# 容器环境变量（一次设置，所有测试生效）
# 来源: tasks/ut/scripts/hf_env.sh - HuggingFace 离线环境配置
# 说明: 远程服务器 t_h20 无外网访问，需使用预下载的本地模型缓存
# 缓存位置: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/
# 已有模型: opt-125m, distilgpt2, Qwen系列等（见 testing.md line 266-270）
#
# 【环境配置说明】
# - 模型/依赖下载服务器: t_ascend (有外网访问，profile: t_ascend)
# - HF 模型下载镜像: https://hf-mirror.com (设置 HF_ENDPOINT)
# - Python 依赖下载路径: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies
# - 依赖下载脚本: skills/ut/dependency-resolver/scripts/download_model.py
# - 详见文档: skills/ut/dependency-resolver/SKILL.md, tasks/ut/docs/guides/testing.md
```

**补充逻辑**:
- Agent 执行 workflow 时读取 workflow.yaml，注释提供关键信息
- 引用相关文档路径，方便 Agent 进一步查阅

---

### Section 5: 失败重试配置与 batch-selector 逻辑修改

**问题根因**:
1. workflow.yaml 缺少失败重试配置参数
2. batch-selector 不选择 failed 状态测试，导致剩余失败测试永远不会被处理

**设计决策（方案 B）**：

**batch-selector 选入 failed 测试的触发条件**：
- **方案 B（已采纳）**：只选 `retry_count < max_retry_per_test` 的 failed 测试
- **原因**：防止无限循环，与 failure-handler 的阈值保护机制一致
- **实现**：batch-selector 增加 retry_count 过滤，manifest.json 记录 retry_count

**修改位置**: 
- `.agents/workflow.yaml` Stage 4 handle_failures 配置
- `skills/ut/batch-selector/SKILL.md` 选择逻辑
- `skills/ut/failure-handler/SKILL.md` retry_count 处理逻辑
- `skills/ut/manifest-updater/SKILL.md` retry_count 写入逻辑
- `skills/ut/shared/manifest_schema.json` retry_count 字段定义

**修改内容**:

#### 1. 补充 workflow.yaml 配置

**当前配置**（Line 200-211）:
```yaml
- id: handle_failures
  delegate_to: self
  skill: failure-handler
  loop: true
  description: 分析失败原因，尝试修复（Agent判断）
  input:
    batch_results_path: *batch_results_path
  output:
    handled_tests_path: *handled_tests_path
  agent_required: true
  timeout: 900
```

**补充配置**:
```yaml
- id: handle_failures
  delegate_to: self
  skill: failure-handler
  loop: true
  description: 分析失败原因，尝试修复（Agent判断）
  input:
    batch_results_path: *batch_results_path
    # 失败重试配置
    max_failed_per_iteration: 10  # 每轮最多处理 10 个失败测试
    max_retry_per_test: 3         # 单测试最多重试 3 次
  output:
    handled_tests_path: *handled_tests_path
  agent_required: true
  timeout: 900
```

#### 2. 修改 batch-selector 逻辑

**当前逻辑**:
- 选择 `pending + fixed_pending_verify`

**修改逻辑**:
- 选择 `pending + fixed_pending_verify + failed`
- 优先级：`fixed_pending_verify > failed > pending`

**代码实现**:
```python
# Step 1: 加载 manifest
manifest = json.loads(Path(manifest_path).read_text())

# 过滤 pending + fixed_pending_verify + failed
pending_tests = [t for t in manifest["tests"] if t["status"] == "pending"]
fixed_pending_tests = [t for t in manifest["tests"] if t["status"] == "fixed_pending_verify"]
failed_tests = [t for t in manifest["tests"] if t["status"] == "failed"]

# 优先级：fixed_pending > failed > pending
# 比例：fixed_pending 30%, failed 40%, pending 30%
batch_tests = []
fixed_limit = batch_size // 3
failed_limit = batch_size // 2

# 1. 验证批次优先（修复后验证）
batch_tests.extend(fixed_pending_tests[:fixed_limit])

# 2. 失败重试批次
remaining_slots = batch_size - len(batch_tests)
batch_tests.extend(failed_tests[:failed_limit])

# 3. 新批次
remaining_slots = batch_size - len(batch_tests)
batch_tests.extend(pending_tests[:remaining_slots])
```

#### 3. 修改 failure-handler 说明

**当前说明**（Line 598-600）:
```
**剩余失败测试：**
- 保持 failed 状态
- 下一轮 batch-selector 自动选择
```

**修改为**:
```
**剩余失败测试：**
- 保持 failed 状态
- 下一轮 batch-selector 自动选择（包含 failed 状态）
- 最多处理 max_failed_per_iteration 个失败测试
- 剩余 failed 状态测试将在后续轮次依次处理
```

**处理流程示例**:
```
Round 1:
  failed_tests = [1-15]（15个失败）
  max_failed_per_iteration = 10
  
  failure-handler:
    - 处理 failed_tests [1-10]
    - 剩余 failed_tests [11-15] 保持 failed 状态
  
  batch-selector (Round 2):
    - 选择 failed_tests [11-15]
    - 选择 pending_tests + fixed_pending_verify
  
  failure-handler (Round 2):
    - 处理 failed_tests [11-15]
    - 所有失败测试处理完毕
```

**配置参数说明**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_failed_per_iteration` | 10 | 每轮最多处理10个失败测试 |
| `max_retry_per_test` | 3 | 单测试最多重试3次（防止无限重试） |
| `batch_size` | 50 | 每批测试总数 |
| `timeout` | 900 | Stage 4 超时时间（秒） |

---

### Section 6: 补充 troubleshooting 文档

**问题根因**:
- 核心 skill 缺少专门的 troubleshooting 文档
- Agent 遇到问题时只能依赖 SKILL.md，缺少问题解决经验积累
- failure-handler、dependency-resolver、workflow 没有 references 目录

**补充位置**:
- `skills/ut/failure-handler/references/troubleshooting.md`
- `skills/ut/dependency-resolver/references/troubleshooting.md`
- `skills/ut/terminal-workflow/references/troubleshooting.md`

**核心原则**:
- **所有错误类型都不能直接 ignored**
- **必须先尝试解决，记录 attempts**
- **达到阈值后才 ignored**
- **脚本优先，Agent判断**（确定性任务用脚本，Agent只处理需要理解的任务）

---

## 分层处理架构

```
┌─────────────────────────────────────────────────────┐
│  失败处理分层架构                                     │
│                                                     │
│  L1 脚本规则：关键词匹配、正则提取、阈值判断          │
│  L2 脚本调用：调用已有脚本（dependency-resolver等）   │
│  L3 脚本定位：traceback解析、代码文件定位            │
│  L4 脚本统计：attempts计数、统计聚合                 │
│                                                     │
│  L5 Agent判断：问题来源分析、修复可行性评估          │
│  L6 Agent生成：代码修复patch、替代方案生成           │
│                                                     │
│  ⚠️ 确定性任务不用 Agent                            │
│  ⚠️ Agent 只处理需要理解的任务                       │
└─────────────────────────────────────────────────────┘
```

**分层处理对照表**：

| 任务 | 层级 | 处理方式 | 原因 |
|------|------|----------|------|
| **检测 GPU 状态** | L1 | 脚本 | 确定性（检测API调用） |
| **延时重试** | L1 | 脚本 | 确定性（固定延时策略） |
| **检查 HF cache** | L1 | 脚本 | 确定性（文件系统检测） |
| **调用 dependency-resolver** | L2 | 脚本 | 固定流程（子 skill） |
| **记录 attempts** | L4 | 脚本 | 数学运算（计数） |
| **判断 attempts >= 3** | L4 | 脚本 | 数学运算（阈值判断） |
| **标记 ignored** | L1 | 脚本 | 确定性（阈值达到后操作） |
| **分析问题来源** | L5 | **Agent** | 需理解上下文（test vs vllm） |
| **判断是否可修复** | L5 | **Agent** | 需理解错误语义 |
| **生成修复 patch** | L6 | **Agent** | 需代码理解和生成 |
| **选择替代模型** | L5 | **Agent** | 需理解测试需求 |

**关键原则**：
1. **确定性任务用脚本**：GPU检测、延时重试、文件检查、计数、阈值判断（不需要 Agent 参与）
2. **Agent 只处理需要理解的任务**：问题来源分析、错误语义理解、代码修复生成、替代方案选择
3. **脚本 + Agent 协作**：脚本执行确定性操作 → Agent判断语义 → 脚本执行后续操作

---

#### 1. failure-handler troubleshooting 文档

**文档内容**:

```markdown
# failure-handler 问题解决手册

## 核心原则

> **重要**：所有错误类型都**不能直接 ignored**，必须先尝试解决，记录 attempts，达到阈值后才 ignored。

**处理流程**：
```
错误 → 尝试解决 → 成功 → retry_test → passed
     ↓
     失败 → attempts += 1
     ↓
     attempts >= max_retry_per_test (3次)
     ↓
     标记 ignored（记录原因）
```

---

## 常见问题分类与处理流程

| 问题类别 | 尝试解决动作 | 重试阈值 | 最终处理 |
|---------|------------|---------|---------|
| **NCCL通信失败** | 检测GPU状态、重试初始化、降级并行度 | 3次 | ignored（环境限制） |
| **依赖下载失败** | 调用 dependency-resolver、检查本地缓存 | 3次 | ignored（无法下载） |
| **模型下载失败** | 检查HF cache、调用下载脚本、使用替代模型 | 3次 | ignored（无模型） |
| **代码修复失败** | Agent生成patch、验证、生成替代方案 | 3次 | ignored（修复失败） |
| **网络超时** | 延时重试（5s/10s/20s）、使用HF mirror | 3次 | ignored（网络问题） |

---

## 问题1：NCCL通信初始化失败

**错误示例**：
```
RuntimeError: NCCL error: unhandled cuda error
```

**尝试解决流程**：

**尝试1：检测GPU状态**
```python
# 脚本检测GPU可用性
gpu_status = detect_gpu_availability()
if gpu_status["available_gpus"] < required_gpus:
    # 等待资源释放
    return {"action": "wait", "blocked_reason": "gpu_unavailable"}
```

**尝试2：重试初始化**
```python
# 延时重试（5s/10s/20s）
for delay in [5, 10, 20]:
    sleep(delay)
    retry_result = retry_test(test["test_node"])
    if retry_result["status"] == "passed":
        test["final_status"] = "passed"
        break
```

**尝试3：降低并行度**
```python
# 降级为单GPU测试
test["test_node"] = adjust_parallel_degree(test["test_node"], world_size=1)
retry_result = retry_test(test["test_node"])
```

**最终处理**（attempts >= 3）：
```python
if attempts >= max_retry_per_test:
    test["final_status"] = "ignored"
    test["ignored_reason"] = f"NCCL initialization failed after {attempts} attempts"
    test["environment_issue"] = True
```

---

## 问题2：模型下载失败

**错误示例**：
```
OSError: cannot connect to huggingface.co
```

**尝试解决流程**：

**尝试1：检查HF cache**
**尝试2：调用 dependency-resolver**
**尝试3：使用替代模型**

（详见文档完整内容）

---

## 问题3：代码修复验证失败

**尝试1：Agent生成patch**
**尝试2：验证修复**
**尝试3：Agent生成替代方案**

（详见文档完整内容）

---

## 重要提醒

1. **不能直接 ignored**：所有错误类型都需尝试解决
2. **记录 attempts**：每次尝试都记录 attempts += 1
3. **阈值保护**：attempts >= max_retry_per_test (3次) 才 ignored
4. **环境问题标记**：最终 ignored 时标记 environment_issue = True
5. **记录原因**：ignored_reason 必须包含尝试次数和失败原因

---

*创建日期: 2026-06-14*
```

---

#### 2. dependency-resolver troubleshooting 文档

**文档内容**:

```markdown
# dependency-resolver 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **HF模型下载失败** | 网络超时、镜像访问失败 | 使用 hf-mirror.com |
| **Python包下载失败** | pip源超时、包不存在 | 使用国内镜像源 |
| **版本冲突** | Triton版本不兼容、API变化 | 安装指定版本 |

---

## 问题1：HF模型下载超时

**错误示例**：
```
ConnectionError: HTTPSConnectionPool(host='huggingface.co', port=443): Max retries exceeded
```

**解决方案**：
```bash
# 设置 HF mirror 镜像
export HF_ENDPOINT=https://hf-mirror.com

# 在 t_ascend 下载模型
python skills/ut/dependency-resolver/scripts/download_model.py \
  --model meta-llama/Llama-3.2-1B-Instruct \
  --hf-dir /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
```

---

## 问题2：Python包不存在

**解决方案**：
```bash
# 在 t_ascend 下载 Python 包（使用镜像）
python skills/ut/dependency-resolver/scripts/install_package.py \
  --package transformers \
  --version 4.40.0 \
  --mirror
```

---

## 问题3：Triton版本不兼容

**解决方案**：
```bash
# 安装兼容版本
pip install triton==2.1.0
```

---

*创建日期: 2026-06-14*
```

---

#### 3. workflow troubleshooting 文档

**文档内容**:

```markdown
# workflow 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **飞书卡片通过率错误** | 显示0.0%（实际33.33%） | 修改 pass_rate 计算 |
| **failed测试未被处理** | batch-selector不选择failed | 增加 failed 选择逻辑 |
| **execution配置未使用** | workflow.yaml有但代码不读 | 删除冗余配置 |

---

## 问题1：飞书卡片通过率显示 0.0%

**解决方案**：
修改 send_progress_card.py，动态计算 pass_rate。

---

## 问题2：failed 测试未被处理

**解决方案**：
修改 batch-selector，增加 failed 测试选择逻辑。

---

## 问题3：execution 配置未被使用

**解决方案**：
删除未使用的 execution 配置块。

---

*创建日期: 2026-06-14*
```

---

## 实施计划

### 修改文件清单

| 文件 | 修改类型 | 修改内容 |
|------|----------|----------|
| `skills/ut/terminal-workflow/scripts/send_progress_card.py` | 代码修改 | 动态计算 pass_rate |
| `.agents/workflow.yaml` | 配置删除 | 删除 execution 配置块 |
| `.agents/workflow.yaml` | 配置调整 | kanban 和 notifications 移到 worker_output_schema 后 |
| `.agents/workflow.yaml` | 注释补充 | container_env 补充环境配置说明 |
| `.agents/workflow.yaml` | 配置补充 | Stage 4 补充 max_failed_per_iteration 和 max_retry_per_test |
| `skills/ut/batch-selector/SKILL.md` | 逻辑修改 | 增加 failed 状态测试选择逻辑 |
| `skills/ut/failure-handler/SKILL.md` | 说明修改 | 更新剩余失败测试处理说明 |
| `skills/ut/failure-handler/references/troubleshooting.md` | **新文件** | failure-handler 问题解决手册 |
| `skills/ut/dependency-resolver/references/troubleshooting.md` | **新文件** | dependency-resolver 问题解决手册 |
| `skills/ut/terminal-workflow/references/troubleshooting.md` | **新文件** | workflow 问题解决手册 |

### 实施步骤

1. **修复飞书卡片通过率**（send_progress_card.py）
2. **删除 execution 配置**（workflow.yaml）
3. **调整配置顺序**（workflow.yaml）
4. **补充环境说明**（workflow.yaml 注释）
5. **补充失败重试配置**（workflow.yaml Stage 4）
6. **修改 batch-selector 逻辑**（batch-selector/SKILL.md）
7. **修改 failure-handler 说明**（failure-handler/SKILL.md）
8. **创建 failure-handler troubleshooting 文档**（新文件）
9. **创建 dependency-resolver troubleshooting 文档**（新文件）
10. **创建 workflow troubleshooting 文档**（新文件）
11. **验证修复**（重新运行 UT Workflow，检查飞书卡片和失败重试流程）

---

## 验收标准

| 标准 | 验收方法 |
|------|----------|
| 飞书卡片通过率正确显示 | 执行 workflow，检查飞书卡片显示 33.33% |
| execution 配置已删除 | 检查 workflow.yaml 无 execution 配置 |
| 配置顺序调整完成 | 检查 workflow.yaml 结构 |
| 环境说明补充完成 | 检查 workflow.yaml 注释包含 t_ascend、HF mirror 等 |
| 失败重试配置补充完成 | 检查 workflow.yaml Stage 4 包含 max_failed_per_iteration 和 max_retry_per_test |
| batch-selector 逻辑修改完成 | 检查 batch-selector/SKILL.md 包含 failed 状态选择逻辑 |
| failure-handler 说明更新完成 | 检查 failure-handler/SKILL.md 说明包含后续轮次处理说明 |
| 失败重试流程验证 | 执行 workflow，验证超过10个失败测试时后续轮次能处理 |
| troubleshooting 文档创建完成 | 检查3个 references 目录包含 troubleshooting.md |
| troubleshooting 文档内容正确 | 检查文档包含"不能直接 ignored"原则和尝试解决流程 |

---

## 影响评估

- ✅ **无破坏性影响**：删除未使用的配置不影响功能
- ✅ **易维护**：减少 workflow.yaml 的复杂度
- ✅ **提升 Agent 知识**：补充环境说明让 Agent 了解配置

---

## 附录：环境配置信息汇总

### 服务器分工

| 服务器 | IP | Profile | 功能 |
|--------|-------|---------|------|
| t_h20 | - | t_h20 | 运行测试（无外网） |
| t_ascend | 10.102.234.45 | t_ascend | 下载模型/依赖（有外网） |

### 环境配置路径

| 配置项 | 路径 |
|--------|------|
| HF_HOME | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub` |
| Python 依赖 | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies` |
| HF mirror | `https://hf-mirror.com` |

### 相关文档

- `skills/ut/dependency-resolver/SKILL.md` - 依赖下载流程
- `tasks/ut/docs/guides/testing.md` - 测试指南
- `tasks/ut/scripts/hf_env.sh` - HF 离线环境配置脚本

---

**设计完成日期**: 2026-06-14
**下一步**: 使用 writing-plans skill 创建实施计划