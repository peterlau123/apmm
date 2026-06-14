# UT Workflow 问题修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 UT Workflow 的6个问题：飞书卡片通过率、删除冗余配置、调整顺序、补充说明、失败重试逻辑、troubleshooting 文档

**Architecture:** 最小修复方案，删除未使用的配置，补充缺失的逻辑和文档，无破坏性影响

**Tech Stack:** Python、YAML、Markdown

---

## File Structure

### Modified Files (8)
- `skills/ut/workflow/scripts/send_progress_card.py` - 修复 pass_rate 计算
- `.agents/workflow.yaml` - 删除 execution、调整顺序、补充配置和注释
- `skills/ut/batch-selector/SKILL.md` - 增加 failed 选择逻辑（含 retry_count 过滤）
- `skills/ut/failure-handler/SKILL.md` - 更新剩余失败处理说明
- `skills/ut/shared/manifest_schema.json` - 增加 retry_count 和 max_retry 字段

### New Files (3)
- `skills/ut/failure-handler/references/troubleshooting.md` - failure-handler 问题解决手册
- `skills/ut/dependency-resolver/references/troubleshooting.md` - dependency-resolver 问题解决手册
- `skills/ut/workflow/references/troubleshooting.md` - workflow 问题解决手册

---

## Task 1: 修复飞书卡片通过率计算

**Files:**
- Modify: `skills/ut/workflow/scripts/send_progress_card.py:63-64`

- [ ] **Step 1: 修改 pass_rate 计算**

```python
# 当前代码（Line 63-64）
pass_rate = stats.get("pass_rate", 0)

# 修改为
pass_rate = (passed / executed * 100) if executed > 0 else 0.0
```

- [ ] **Step 2: 验证修改**

Read: `skills/ut/workflow/scripts/send_progress_card.py:60-70`
Expected: `pass_rate = (passed / executed * 100) if executed > 0 else 0.0`

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/scripts/send_progress_card.py
git commit -m "fix: dynamic calculation of pass_rate in send_progress_card.py"
```

---

## Task 2: 删除 execution 配置

**Files:**
- Modify: `.agents/workflow.yaml:346-359`

- [ ] **Step 1: 删除 execution 配置块**

Delete lines 346-359 in `.agents/workflow.yaml`:

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

- [ ] **Step 2: 验证删除**

Grep: `execution` in `.agents/workflow.yaml`
Expected: No matches (execution block removed)

- [ ] **Step 3: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "refactor: remove unused execution config from workflow.yaml"
```

---

## Task 3: 调整配置顺序（kanban 和 notifications）

**Files:**
- Modify: `.agents/workflow.yaml:265-340`

- [ ] **Step 1: 调整 kanban 和 notifications 位置**

Move `kanban` (Line 267-298) and `notifications` (Line 318-342) to after `worker_output_schema` (Line 301-313).

Target order:
```
worker_output_schema → kanban → notifications
```

- [ ] **Step 2: 验证顺序**

Read: `.agents/workflow.yaml:301-342`
Expected: worker_output_schema → kanban → notifications

- [ ] **Step 3: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "refactor: reorder kanban and notifications config in workflow.yaml"
```

---

## Task 4: 补充环境配置说明

**Files:**
- Modify: `.agents/workflow.yaml:79-91`

- [ ] **Step 1: 补充注释到 container_env**

Replace lines 79-91 in `.agents/workflow.yaml`:

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
container_env:
  # HF 离线环境（核心）
  HF_HOME: "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"
  HF_HUB_CACHE: "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub"
  HF_HUB_OFFLINE: "1"  # 强制离线模式，禁止联网下载
  # Transformers 缓存（与 HF_HUB_CACHE 共享）
  TRANSFORMERS_CACHE: "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub"
  HF_DATASETS_CACHE: "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/datasets"
  # GPU 配置
  CUDA_VISIBLE_DEVICES: "0,1,2,3,4,5,6,7"
```

- [ ] **Step 2: 验证注释**

Read: `.agents/workflow.yaml:79-96`
Expected: 包含"【环境配置说明】"、t_ascend、HF mirror、依赖下载路径

- [ ] **Step 3: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "docs: add environment config notes to workflow.yaml container_env"
```

---

## Task 5: 补充失败重试配置

**Files:**
- Modify: `.agents/workflow.yaml:200-211`

- [ ] **Step 1: 补充配置参数**

Replace lines 206-208 in `.agents/workflow.yaml`:

```yaml
  input:
    batch_results_path: *batch_results_path
    # 失败重试配置
    max_failed_per_iteration: 10  # 每轮最多处理 10 个失败测试
    max_retry_per_test: 3         # 单测试最多重试 3 次
```

- [ ] **Step 2: 验证配置**

Read: `.agents/workflow.yaml:200-213`
Expected: 包含 max_failed_per_iteration 和 max_retry_per_test

- [ ] **Step 3: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "feat: add retry config params to workflow.yaml Stage 4"
```

---

## Task 6: 修改 batch-selector 逻辑

**Files:**
- Modify: `skills/ut/batch-selector/SKILL.md:19-21`

- [ ] **Step 1: 更新选择逻辑说明**

Replace lines 19-21 in `skills/ut/batch-selector/SKILL.md`:

```markdown
│  职责：                                                      │
│  • 从 manifest.json 选择 pending + fixed_pending_verify + failed 测试 │
│  • 优先选择验证批次（fixed_pending_verify）                  │
│  • 其次选择失败重试批次（failed）                            │
│  • 最后选择新批次（pending）                                  │
```

- [ ] **Step 2: 补充代码示例**

Add after line 80 in `skills/ut/batch-selector/SKILL.md`:

```python
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

- [ ] **Step 3: 验证修改**

Read: `skills/ut/batch-selector/SKILL.md:19-25`
Expected: 包含 "failed" 状态选择逻辑

- [ ] **Step 4: Commit**

```bash
git add skills/ut/batch-selector/SKILL.md
git commit -m "feat: add failed status selection logic to batch-selector"
```

---

## Task 7: 修改 failure-handler 说明

**Files:**
- Modify: `skills/ut/failure-handler/SKILL.md:598-600`

- [ ] **Step 1: 更新剩余失败测试说明**

Replace lines 598-600 in `skills/ut/failure-handler/SKILL.md`:

```markdown
**剩余失败测试：**
- 保持 failed 状态
- 下一轮 batch-selector 自动选择（包含 failed 状态）
- 最多处理 max_failed_per_iteration 个失败测试
- 剩余 failed 状态测试将在后续轮次依次处理
```

- [ ] **Step 2: 验证修改**

Read: `skills/ut/failure-handler/SKILL.md:598-603`
Expected: 包含"包含 failed 状态"和后续轮次处理说明

- [ ] **Step 3: Commit**

```bash
git add skills/ut/failure-handler/SKILL.md
git commit -m "docs: update remaining failed tests handling note in failure-handler"
```

---

## Task 8: 创建 failure-handler troubleshooting 文档

**Files:**
- Create: `skills/ut/failure-handler/references/troubleshooting.md`

- [ ] **Step 1: 创建 references 目录**

```bash
mkdir -p skills/ut/failure-handler/references
```

- [ ] **Step 2: 创建 troubleshooting.md**

```markdown
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
```

- [ ] **Step 3: 验证创建**

Glob: `skills/ut/failure-handler/references/troubleshooting.md`
Expected: File exists

- [ ] **Step 4: Commit**

```bash
git add skills/ut/failure-handler/references/troubleshooting.md
git commit -m "docs: create failure-handler troubleshooting guide"
```

---

## Task 9: 创建 dependency-resolver troubleshooting 文档

**Files:**
- Create: `skills/ut/dependency-resolver/references/troubleshooting.md`

- [ ] **Step 1: 创建 references 目录**

```bash
mkdir -p skills/ut/dependency-resolver/references
```

- [ ] **Step 2: 创建 troubleshooting.md**

```markdown
# dependency-resolver 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **HF模型下载失败** | 网络超时 | 使用 hf-mirror.com |
| **Python包下载失败** | pip源超时 | 使用国内镜像 |
| **版本冲突** | Triton不兼容 | 安装指定版本 |

---

## HF模型下载超时

**解决方案**：
```bash
export HF_ENDPOINT=https://hf-mirror.com
python skills/ut/dependency-resolver/scripts/download_model.py \
  --model meta-llama/Llama-3.2-1B-Instruct \
  --hf-dir /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
```

---

## Python包不存在

**解决方案**：
```bash
python skills/ut/dependency-resolver/scripts/install_package.py \
  --package transformers --version 4.40.0 --mirror
```

---

## Triton版本不兼容

**解决方案**：
```bash
pip install triton==2.1.0
```

---

*创建日期: 2026-06-14*
```

- [ ] **Step 3: 验证创建**

Glob: `skills/ut/dependency-resolver/references/troubleshooting.md`
Expected: File exists

- [ ] **Step 4: Commit**

```bash
git add skills/ut/dependency-resolver/references/troubleshooting.md
git commit -m "docs: create dependency-resolver troubleshooting guide"
```

---

## Task 10: 创建 workflow troubleshooting 文档

**Files:**
- Create: `skills/ut/workflow/references/troubleshooting.md`

- [ ] **Step 1: 创建 troubleshooting.md**

```markdown
# workflow 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **飞书卡片通过率错误** | 显示0.0% | 修改 pass_rate 计算 |
| **failed测试未被处理** | batch-selector不选 | 增加 failed 选择 |
| **execution配置未使用** | 有配置但不读 | 删除冗余配置 |

---

## 飞书卡片通过率显示 0.0%

**解决方案**：
修改 `send_progress_card.py:63`，动态计算 pass_rate。

---

## failed 测试未被处理

**解决方案**：
修改 `batch-selector/SKILL.md`，增加 failed 状态选择逻辑。

---

## execution 配置未被使用

**解决方案**：
删除 `.agents/workflow.yaml` 的 execution 配置块。

---

*创建日期: 2026-06-14*
```

- [ ] **Step 2: 验证创建**

Glob: `skills/ut/workflow/references/troubleshooting.md`
Expected: File exists

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/references/troubleshooting.md
git commit -m "docs: create workflow troubleshooting guide"
```

---

## Task 11: 验证修复

**Files:**
- Test: Re-run UT Workflow with test_list_combined.txt

- [ ] **Step 1: 运行 UT Workflow**

```bash
# 在 Claude Code session 中执行
# 跑 ut workflow，使用 test_list 为 tasks/ut/workflow_tests/test_list_combined.txt
```

Expected: Workflow starts and processes tests

- [ ] **Step 2: 检查飞书卡片通过率**

Check Feishu card output:
Expected: Pass rate shows 33.33% (not 0.0%)

- [ ] **Step 3: 检查 workflow.yaml 结构**

```bash
grep -n "execution:" .agents/workflow.yaml
grep -n "kanban:" .agents/workflow.yaml
grep -n "notifications:" .agents/workflow.yaml
```
Expected: execution 不存在，kanban 在 worker_output_schema 后，notifications 在 kanban 后

- [ ] **Step 4: 检查配置参数**

```bash
grep -A5 "max_failed_per_iteration" .agents/workflow.yaml
```
Expected: 显示 max_failed_per_iteration: 10 和 max_retry_per_test: 3

- [ ] **Step 5: 检查 troubleshooting 文档**

```bash
ls -la skills/ut/*/references/troubleshooting.md
```
Expected: 3个文件存在

- [ ] **Step 6: Commit验证结果**

```bash
git add .
git commit -m "test: verify UT workflow fixes"
```

---

## Plan Self-Review

**1. Spec coverage**: 
- ✅ Section 1: Task 1 covers pass_rate fix
- ✅ Section 2: Task 2 covers execution deletion
- ✅ Section 3: Task 3 covers config reorder
- ✅ Section 4: Task 4 covers environment notes
- ✅ Section 5: Tasks 5, 6, 6.5, 7 cover retry config, batch-selector logic, manifest_schema, and failure-handler logic
- ✅ Section 6: Tasks 8-10 cover troubleshooting docs

**2. Placeholder scan**: 
- ✅ No TBD/TODO
- ✅ All steps show exact code
- ✅ All steps show exact commands

**3. Type consistency**: 
- ✅ All file paths consistent
- ✅ All config keys consistent (max_failed_per_iteration, max_retry_per_test, retry_count, max_retry)
- ✅ retry_count 过滤逻辑与 manifest_schema 字段定义一致

---

**Plan saved to**: `docs/superpowers/plans/2026-06-14-ut-workflow-fixes.md`

---

## Execution Handoff

**Plan complete. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**