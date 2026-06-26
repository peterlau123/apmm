# UT Skills & Profiles Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重组UT skills和profiles结构，实现职责清晰、修改一处生效、Linear/Kanban模式分离

**Architecture:** Supervisor（hermes-workflow）负责监控+调度，5个Worker（Stage2-5）各自执行具体Stage，Stage1由Supervisor直接执行。每个Worker skill添加SOUL.md身份定义，dependency-resolver保持独立作为子skill。

**Tech Stack:** Python 3.11+, Hermes profiles, pytest, YAML configuration

---

## File Structure

### 创建的文件

| 文件 | 职责 |
|------|------|
| `skills/ut/batch-selector/SOUL.md` | Stage2 Worker身份定义（ut-batch-selector） |
| `skills/ut/unit-test-executor/SOUL.md` | Stage3 Worker身份定义（ut-executor） |
| `skills/ut/failure-handler/SOUL.md` | Stage4 Worker身份定义（ut-fixer） |
| `skills/ut/manifest-updater/SOUL.md` | Stage5 Worker身份定义（ut-manifest-updater） |
| `tasks/ut/scripts/.dist/ut-batch-selector/profile.yaml` | Stage2 Worker profile配置 |
| `tasks/ut/scripts/.dist/ut-manifest-updater/profile.yaml` | Stage5 Worker profile配置 |
| `skills/ut/hermes_workflow/scripts/kanban_task_creator.py` | Kanban task创建逻辑 |
| `skills/ut/hermes_workflow/scripts/orchestrator_round.py` | Kanban调度循环逻辑 |

### 重命名的文件

| 原路径 | 新路径 | 原因 |
|--------|--------|------|
| `skills/ut/workflow` | `skills/ut/terminal-workflow` | 线性通道命名清晰化（vs hermes通道） |
| `skills/ut/ut-test-collector` | `skills/ut/unit-test-collector` | 前缀一致性（去掉ut-） |

### 修改的文件

| 文件 | 修改内容 |
|------|----------|
| `skills/ut/terminal-workflow/SKILL.md` | 更新name字段从workflow→terminal-workflow |
| `skills/ut/unit-test-collector/SKILL.md` | 更新name字段从ut-test-collector→unit-test-collector |
| `tasks/ut/scripts/deploy_tier.py` | 更新profile数量（5个Worker）和skills加载逻辑 |

---

## Phase 1: Skills 目录重组

### Task 1: 重命名 workflow → terminal-workflow

**Files:**
- Rename: `skills/ut/workflow` → `skills/ut/terminal-workflow`
- Modify: `skills/ut/terminal-workflow/SKILL.md`

- [ ] **Step 1: 重命名目录**

```bash
cd skills/ut
mv workflow terminal-workflow
```

验证：`ls skills/ut/terminal-workflow/SKILL.md` 应存在

- [ ] **Step 2: 更新SKILL.md name字段**

读取 `skills/ut/terminal-workflow/SKILL.md`，修改frontmatter：

```yaml
---
name: terminal-workflow  # 从 workflow 改为 terminal-workflow
description: 线性通道（终端Agent用）- 5阶段流水线总控
version: 2.0.0
when_to_use: 终端Agent执行UT workflow（无Hermes通道）
---
```

- [ ] **Step 3: 验证修改**

```bash
grep "^name:" skills/ut/terminal-workflow/SKILL.md
```

预期输出：`name: terminal-workflow`

- [ ] **Step 4: Commit**

```bash
git add skills/ut/terminal-workflow/
git commit -m "refactor(ut): rename workflow → terminal-workflow (linear channel)"
```

---

### Task 2: 重命名 ut-test-collector → unit-test-collector

**Files:**
- Rename: `skills/ut/ut-test-collector` → `skills/ut/unit-test-collector`
- Modify: `skills/ut/unit-test-collector/SKILL.md`

- [ ] **Step 1: 重命名目录**

```bash
cd skills/ut
mv ut-test-collector unit-test-collector
```

验证：`ls skills/ut/unit-test-collector/SKILL.md` 应存在

- [ ] **Step 2: 更新SKILL.md name字段**

修改frontmatter：

```yaml
---
name: unit-test-collector  # 从 ut-test-collector 改为 unit-test-collector
description: Worker Agent - 测试清单收集，生成完整 manifest.json
version: 2.1.0
when_to_use: 作为 Worker Agent 被 Supervisor 调用，执行 collect Stage
---
```

- [ ] **Step 3: 验证修改**

```bash
grep "^name:" skills/ut/unit-test-collector/SKILL.md
```

预期输出：`name: unit-test-collector`

- [ ] **Step 4: Commit**

```bash
git add skills/ut/unit-test-collector/
git commit -m "refactor(ut): rename ut-test-collector → unit-test-collector (prefix consistency)"
```

---

### Task 3: 添加 batch-selector SOUL.md

**Files:**
- Create: `skills/ut/batch-selector/SOUL.md`

- [ ] **Step 1: 创建SOUL.md**

写入文件内容：

```markdown
# ut-batch-selector Identity

## Role
Stage 2 Worker - 批次选择器

## Responsibilities
- 从 manifest.json 选择测试批次
- 应用批次策略（批大小、优先级）
- 处理 fixed_pending_verify 验证批次
- 创建 Kanban 依赖链（executor → fixer → manifest-updater → next batch-selector）

## Boundaries
- **不发送飞书通知**：Supervisor 负责
- **不执行测试**：Executor Worker 负责
- **不修复失败**：Fixer Worker 负责

## Context Usage
- Linear mode: 由 Supervisor 加载，完整上下文
- Kanban mode: 独立加载，只看 batch-selector skill

## Communication
- 输入: manifest.json（Supervisor传递）
- 输出: batch_config.json
- 返回: stats（极简）给 Supervisor

## Troubleshooting References
- SKILL.md 内联常见问题
- references/ 存放复杂问题文档
```

- [ ] **Step 2: 验证文件**

```bash
cat skills/ut/batch-selector/SOUL.md
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add skills/ut/batch-selector/SOUL.md
git commit -m "feat(ut): add batch-selector SOUL.md (Stage2 Worker identity)"
```

---

### Task 4: 添加 unit-test-executor SOUL.md

**Files:**
- Create: `skills/ut/unit-test-executor/SOUL.md`

- [ ] **Step 1: 创建SOUL.md**

写入文件内容：

```markdown
# ut-executor Identity

## Role
Stage 3 Worker - 测试执行器

## Responsibilities
- 执行 pytest 测试批次
- GPU 检测与分配
- Watchdog timeout 控制
- 生成 batch_results.json

## Boundaries
- **不发送飞书通知**：Supervisor 负责
- **不选择批次**：Batch-selector Worker 负责
- **不修复失败**：Fixer Worker 负责

## Context Usage
- Linear mode: 由 Supervisor 加载，完整上下文
- Kanban mode: 独立加载，只看 unit-test-executor skill

## Communication
- 输入: batch_config.json（Batch-selector传递）
- 输出: batch_results.json + remote log
- 返回: stats（极简）给 Supervisor

## Troubleshooting References
- SKILL.md 内联常见问题（watchdog timeout、GPU OOM）
- references/watchdog-timeout.md（复杂问题）
- references/remote-execution.md（执行细节）
```

- [ ] **Step 2: 验证文件**

```bash
cat skills/ut/unit-test-executor/SOUL.md
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add skills/ut/unit-test-executor/SOUL.md
git commit -m "feat(ut): add unit-test-executor SOUL.md (Stage3 Worker identity)"
```

---

### Task 5: 添加 failure-handler SOUL.md

**Files:**
- Create: `skills/ut/failure-handler/SOUL.md`

- [ ] **Step 1: 创建SOUL.md**

写入文件内容：

```markdown
# ut-fixer Identity

## Role
Stage 4 Worker - 失败处理器

## Responsibilities
- 分析失败原因（error/failure分类）
- 尝试修复代码（远程容器）
- 调用 dependency-resolver 子 skill（依赖下载）
- 生成 handled_tests.json
- 验证修复效果 → fixed_pending_verify

## Boundaries
- **不发送飞书通知**：Supervisor 负责
- **不选择批次**：Batch-selector Worker 负责
- **不执行测试**：Executor Worker 负责
- **不修改 manifest.json**：Manifest-updater Worker 负责

## Context Usage
- Linear mode: 由 Supervisor 加载，完整上下文
- Kanban mode: 独立加载，只看 failure-handler skill + dependency-resolver 子 skill

## Communication
- 输入: batch_results.json（Executor传递）
- 输出: handled_tests.json
- 返回: stats（极简）给 Supervisor

## Troubleshooting References
- SKILL.md 内联常见问题（error分类、修复策略）
- references/error-type-classification.md（分类细节）
- references/dependency-resolution.md（依赖处理）
```

- [ ] **Step 2: 验证文件**

```bash
cat skills/ut/failure-handler/SOUL.md
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add skills/ut/failure-handler/SOUL.md
git commit -m "feat(ut): add failure-handler SOUL.md (Stage4 Worker identity, fixer)"
```

---

### Task 6: 添加 manifest-updater SOUL.md

**Files:**
- Create: `skills/ut/manifest-updater/SOUL.md`

- [ ] **Step 1: 创建SOUL.md**

写入文件内容：

```markdown
# ut-manifest-updater Identity

## Role
Stage 5 Worker - Manifest 更新器

## Responsibilities
- 更新 manifest.json（测试状态）
- 写入 errors[]/failures[] 历史
- 更新 resolved_errors/resolved_failures 索引
- 统计 pass rate / progress

## Boundaries
- **不发送飞书通知**：Supervisor 负责
- **不选择批次**：Batch-selector Worker 负责
- **不执行测试**：Executor Worker 负责
- **不修复失败**：Fixer Worker 负责

## Context Usage
- Linear mode: 由 Supervisor 加载，完整上下文
- Kanban mode: 独立加载，只看 manifest-updater skill

## Communication
- 输入: batch_results.json + handled_tests.json
- 输出: manifest.json（更新）
- 返回: stats（极简）给 Supervisor

## Troubleshooting References
- SKILL.md 内联常见问题（状态流转、索引更新）
```

- [ ] **Step 2: 验证文件**

```bash
cat skills/ut/manifest-updater/SOUL.md
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add skills/ut/manifest-updater/SOUL.md
git commit -m "feat(ut): add manifest-updater SOUL.md (Stage5 Worker identity)"
```

---

## Phase 2: Profile 配置调整

### Task 7: 创建 ut-batch-selector profile.yaml

**Files:**
- Create: `tasks/ut/scripts/.dist/ut-batch-selector/profile.yaml`

- [ ] **Step 1: 创建profile.yaml**

写入文件内容：

```yaml
description: 'UT Workflow Stage2 Worker: batch-selector'

x-deploy:
  auto_load_skills:
    - ut/batch-selector
    - ut/workflow_loop_core
    - ut/shared

  # Kanban mode: 只加载 Stage2 skill
  # Linear mode: 由 ut-supervisor 加载（不需要此profile）
```

- [ ] **Step 2: 验证文件**

```bash
cat tasks/ut/scripts/.dist/ut-batch-selector/profile.yaml
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add tasks/ut/scripts/.dist/ut-batch-selector/profile.yaml
git commit -m "feat(ut): create ut-batch-selector profile.yaml (Stage2 Worker Kanban config)"
```

---

### Task 8: 创建 ut-manifest-updater profile.yaml

**Files:**
- Create: `tasks/ut/scripts/.dist/ut-manifest-updater/profile.yaml`

- [ ] **Step 1: 创建profile.yaml**

写入文件内容：

```yaml
description: 'UT Workflow Stage5 Worker: manifest-updater'

x-deploy:
  auto_load_skills:
    - ut/manifest-updater
    - ut/workflow_loop_core
    - ut/shared

  # Kanban mode: 只加载 Stage5 skill
  # Linear mode: 由 ut-supervisor 加载（不需要此profile）
```

- [ ] **Step 2: 验证文件**

```bash
cat tasks/ut/scripts/.dist/ut-manifest-updater/profile.yaml
```

应看到完整内容

- [ ] **Step 3: Commit**

```bash
git add tasks/ut/scripts/.dist/ut-manifest-updater/profile.yaml
git commit -m "feat(ut): create ut-manifest-updater profile.yaml (Stage5 Worker Kanban config)"
```

---

### Task 9: 更新 deploy_tier.py profile数量

**Files:**
- Modify: `tasks/ut/scripts/deploy_tier.py`

- [ ] **Step 1: 查看当前profile配置**

```bash
grep -A 20 "_PROFILE_SKILLS" tasks/ut/scripts/deploy_tier.py
```

预期看到：ut-supervisor, ut-orchestrator, ut-executor, ut-fixer

- [ ] **Step 2: 更新profile配置**

在 `_PROFILE_SKILLS` dict中添加：

```python
_PROFILE_SKILLS = {
    "ut-supervisor": [
        "hermes_workflow", "workflow_loop_core",
        "batch-selector", "unit-test-executor", "failure-handler", "manifest-updater",  # Linear mode 加载所有 Worker
        "shared"
    ],
    "ut-orchestrator": ["batch-selector", "manifest-updater"],  # 已存在，保持不变
    "ut-executor": ["unit-test-executor"],  # 已存在，保持不变
    "ut-fixer": ["failure-handler", "dependency-resolver"],  # 已存在，dependency-resolver 作为子 skill
    "ut-batch-selector": ["batch-selector", "workflow_loop_core", "shared"],  # 新增：Stage2 Worker Kanban profile
    "ut-manifest-updater": ["manifest-updater", "workflow_loop_core", "shared"],  # 新增：Stage5 Worker Kanban profile
}
```

- [ ] **Step 3: 验证修改**

```bash
grep -A 10 "ut-batch-selector" tasks/ut/scripts/deploy_tier.py
```

应看到新增的profile配置

- [ ] **Step 4: Commit**

```bash
git add tasks/ut/scripts/deploy_tier.py
git commit -m "refactor(ut): update deploy_tier.py for 5 Worker profiles (Stage2-5)"
```

---

## Phase 3: Kanban 调度逻辑

### Task 10: 创建 kanban_task_creator.py

**Files:**
- Create: `skills/ut/hermes_workflow/scripts/kanban_task_creator.py`

- [ ] **Step 1: 创建脚本框架**

写入文件内容：

```python
"""
Kanban Task Creator - 创建 Kanban task + 依赖链

职责：
1. Supervisor 创建第一个 batch-selector task（启动流程）
2. batch-selector 完成后创建后续依赖链（executor → fixer → manifest-updater → next batch-selector）
3. batch-selector 返回空时终止循环

设计文档：§5.1 任务依赖链
"""

import json
from pathlib import Path
from typing import Dict, List, Optional


def create_initial_task(manifest_path: str, run_dir: str) -> Dict:
    """
    Supervisor 创建第一个 batch-selector task

    Args:
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径

    Returns:
        task_config: Kanban task 配置
    """
    manifest = json.loads(Path(manifest_path).read_text())

    # 检查是否有 pending 测试
    pending_tests = [t for t in manifest["tests"] if t["status"] == "pending"]
    if not pending_tests:
        return {"status": "empty", "reason": "no pending tests"}

    # 创建 batch-selector task
    task_config = {
        "task_name": "batch-selector-round-1",
        "profile": "ut-batch-selector",
        "context": {
            "manifest_path": manifest_path,
            "run_dir": run_dir,
            "round": 1,
        },
        "parents": [],  # 第一个 task 无依赖
    }

    return task_config


def create_dependency_chain(
    batch_result: Dict,
    manifest_path: str,
    run_dir: str,
    current_round: int,
) -> Optional[List[Dict]]:
    """
    batch-selector 完成后创建后续依赖链

    Args:
        batch_result: batch-selector 返回结果（batch_config.json）
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径
        current_round: 当前轮次

    Returns:
        dependency_chain: executor → fixer → manifest-updater → next batch-selector
        None: 如果 batch-selector 返回空（循环终止）
    """
    # 检查 batch 是否为空
    if batch_result.get("status") == "empty":
        return None  # 循环终止，不发飞书（Supervisor 监控会处理）

    # 创建依赖链
    executor_task = {
        "task_name": f"executor-round-{current_round}",
        "profile": "ut-executor",
        "context": {
            "batch_config_path": f"{run_dir}/batch_config.json",
            "run_dir": run_dir,
        },
        "parents": [f"batch-selector-round-{current_round}"],
    }

    fixer_task = {
        "task_name": f"fixer-round-{current_round}",
        "profile": "ut-fixer",
        "context": {
            "batch_results_path": f"{run_dir}/batch_results.json",
            "manifest_path": manifest_path,
            "run_dir": run_dir,
        },
        "parents": [f"executor-round-{current_round}"],
    }

    manifest_updater_task = {
        "task_name": f"manifest-updater-round-{current_round}",
        "profile": "ut-manifest-updater",
        "context": {
            "batch_results_path": f"{run_dir}/batch_results.json",
            "handled_tests_path": f"{run_dir}/handled_tests.json",
            "manifest_path": manifest_path,
            "run_dir": run_dir,
        },
        "parents": [f"fixer-round-{current_round}"],
    }

    # 创建 next batch-selector task（下一轮）
    next_batch_selector_task = {
        "task_name": f"batch-selector-round-{current_round + 1}",
        "profile": "ut-batch-selector",
        "context": {
            "manifest_path": manifest_path,
            "run_dir": run_dir,
            "round": current_round + 1,
        },
        "parents": [f"manifest-updater-round-{current_round}"],
    }

    return [executor_task, fixer_task, manifest_updater_task, next_batch_selector_task]


def save_tasks_to_kanban(tasks: List[Dict], kanban_file: str) -> None:
    """
    保存 tasks 到 Kanban 文件（JSON Lines）

    Args:
        tasks: task 配置列表
        kanban_file: Kanban 文件路径
    """
    with open(kanban_file, "a") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")


# 测试入口（手动验证）
if __name__ == "__main__":
    # 测试 create_initial_task
    manifest_path = "tests/ut/integration/fixtures/test_manifest.json"
    run_dir = "tests/ut/integration/fixtures/run_dir"

    task = create_initial_task(manifest_path, run_dir)
    print(f"Initial task: {json.dumps(task, indent=2)}")

    # 测试 create_dependency_chain
    batch_result = {"status": "non_empty", "batch_id": "batch-001"}
    chain = create_dependency_chain(batch_result, manifest_path, run_dir, 1)
    if chain:
        print(f"Dependency chain: {json.dumps(chain, indent=2)}")
    else:
        print("Loop terminated (batch empty)")
```

- [ ] **Step 2: 验证脚本**

```bash
python skills/ut/hermes_workflow/scripts/kanban_task_creator.py
```

预期输出：显示 initial task 和 dependency chain（需要测试fixtures）

- [ ] **Step 3: Commit**

```bash
git add skills/ut/hermes_workflow/scripts/kanban_task_creator.py
git commit -m "feat(ut): add kanban_task_creator.py (Supervisor → batch-selector dependency chain)"
```

---

### Task 11: 创建 orchestrator_round.py

**Files:**
- Create: `skills/ut/hermes_workflow/scripts/orchestrator_round.py`

- [ ] **Step 1: 创建脚本框架**

写入文件内容：

```python
"""
Orchestrator Round - Kanban 调度循环逻辑

职责：
1. 监控 batch-selector task 完成状态
2. 调用 kanban_task_creator 创建依赖链
3. 提交 tasks 到 Hermes Kanban
4. 循环直到 batch-selector 返回空

设计文档：§5.2 调度逻辑
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional

from .kanban_task_creator import create_dependency_chain, save_tasks_to_kanban


def check_task_completion(task_name: str, kanban_file: str) -> bool:
    """
    检查 task 是否完成

    Args:
        task_name: task 名称
        kanban_file: Kanban 文件路径

    Returns:
        True: task 已完成
        False: task 未完成
    """
    if not Path(kanban_file).exists():
        return False

    with open(kanban_file) as f:
        for line in f:
            task = json.loads(line)
            if task.get("task_name") == task_name:
                return task.get("status") == "completed"

    return False


def orchestrator_loop(
    manifest_path: str,
    run_dir: str,
    kanban_file: str,
    max_rounds: int = 100,
) -> Dict:
    """
    Kanban 调度循环

    Args:
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径
        kanban_file: Kanban 文件路径
        max_rounds: 最大轮次（防止无限循环）

    Returns:
        result: {
            "status": "completed",
            "total_rounds": N,
            "total_tests": M,
            "pass_rate": X,
        }
    """
    current_round = 1

    while current_round <= max_rounds:
        # Step 1: 等待 batch-selector task 完成
        batch_selector_task = f"batch-selector-round-{current_round}"

        # Polling 等待（简化实现，实际应使用 Hermes webhook）
        while not check_task_completion(batch_selector_task, kanban_file):
            time.sleep(5)  # 5秒 polling间隔

        # Step 2: 读取 batch-selector 结果
        batch_config_path = f"{run_dir}/batch_config.json"
        batch_result = json.loads(Path(batch_config_path).read_text())

        # Step 3: 创建依赖链
        dependency_chain = create_dependency_chain(
            batch_result, manifest_path, run_dir, current_round
        )

        # Step 4: 检查循环终止条件
        if dependency_chain is None:
            # batch-selector 返回空，循环终止
            manifest = json.loads(Path(manifest_path).read_text())
            stats = manifest.get("statistics", {})

            return {
                "status": "completed",
                "total_rounds": current_round,
                "total_tests": stats.get("total", 0),
                "pass_rate": stats.get("pass_rate", 0),
            }

        # Step 5: 提交依赖链到 Kanban
        save_tasks_to_kanban(dependency_chain, kanban_file)

        # Step 6: 进入下一轮
        current_round += 1

    # 达到 max_rounds，返回异常
    return {
        "status": "max_rounds_exceeded",
        "total_rounds": current_round,
        "reason": f"Reached max_rounds limit ({max_rounds})",
    }


# 测试入口（手动验证）
if __name__ == "__main__":
    manifest_path = "tests/ut/integration/fixtures/test_manifest.json"
    run_dir = "tests/ut/integration/fixtures/run_dir"
    kanban_file = "tests/ut/integration/fixtures/kanban_tasks.jsonl"

    # 清空 kanban_file
    Path(kanban_file).write_text("")

    # 运行调度循环（需要模拟 batch-selector 完成）
    result = orchestrator_loop(manifest_path, run_dir, kanban_file, max_rounds=3)
    print(f"Orchestrator result: {json.dumps(result, indent=2)}")
```

- [ ] **Step 2: 验证脚本**

```bash
python skills/ut/hermes_workflow/scripts/orchestrator_round.py
```

预期输出：显示 orchestrator result（需要测试fixtures）

- [ ] **Step 3: Commit**

```bash
git add skills/ut/hermes_workflow/scripts/orchestrator_round.py
git commit -m "feat(ut): add orchestrator_round.py (Kanban scheduling loop logic)"
```

---

## Phase 4: 测试验证

### Task 12: 测试 Linear mode（L1-L3）

**Files:**
- Test: Integration test for Linear mode

- [ ] **Step 1: 准备测试环境**

```bash
# 检查 L1-L3 fixtures
ls tests/ut/integration/fixtures/workflow.l*.yaml
```

预期看到：workflow.l1.yaml, workflow.l2.yaml, workflow.l3.yaml

- [ ] **Step 2: 运行 L1 测试**

```bash
python tasks/ut/scripts/start_gateway.py --workflow tests/ut/integration/fixtures/workflow.l1.yaml
```

预期：Supervisor 加载所有 Worker skills（完整上下文），执行Stage1-5

- [ ] **Step 3: 验证 Linear mode skills加载**

检查hermes_runner.py加载逻辑：

```bash
grep -A 20 "auto_load_skills" tasks/ut/scripts/.dist/ut-supervisor/profile.yaml
```

预期看到：hermes-workflow + loop_core + unit-test-collector + batch-selector + unit-test-executor + failure-handler + manifest-updater + shared

- [ ] **Step 4: 运行 L2/L3 测试（重复Step 2）**

验证不同tier的Linear mode都能正常执行

- [ ] **Step 5: Commit**

```bash
git add tests/ut/integration/fixtures/
git commit -m "test(ut): verify Linear mode (L1-L3) with complete context loading"
```

---

### Task 13: 测试 Kanban mode（L4）

**Files:**
- Test: Integration test for Kanban mode

- [ ] **Step 1: 准备测试环境**

```bash
# 检查 L4 fixtures
ls tests/ut/integration/fixtures/workflow.l4.yaml
```

预期看到：workflow.l4.yaml

- [ ] **Step 2: 创建测试Kanban tasks**

模拟Supervisor创建第一个batch-selector task：

```bash
python skills/ut/hermes_workflow/scripts/kanban_task_creator.py > tests/ut/integration/fixtures/kanban_tasks.jsonl
```

- [ ] **Step 3: 运行 L4 测试**

```bash
python tasks/ut/scripts/start_gateway.py --workflow tests/ut/integration/fixtures/workflow.l4.yaml --kanban tests/ut/integration/fixtures/kanban_tasks.jsonl
```

预期：Supervisor只加载hermes-workflow + loop_core + shared，5个Worker各自加载专有skill

- [ ] **Step 4: 验证 Kanban mode profiles加载**

检查Worker profiles：

```bash
cat tasks/ut/scripts/.dist/ut-batch-selector/profile.yaml
cat tasks/ut/scripts/.dist/ut-executor/profile.yaml
cat tasks/ut/scripts/.dist/ut-fixer/profile.yaml
cat tasks/ut/scripts/.dist/ut-manifest-updater/profile.yaml
```

预期：每个Worker只加载自己的skill + loop_core + shared

- [ ] **Step 5: 验证 Kanban调度循环**

检查orchestrator_round.py输出：

```bash
python skills/ut/hermes_workflow/scripts/orchestrator_round.py
```

预期：显示调度循环结果，循环终止条件正确

- [ ] **Step 6: Commit**

```bash
git add tests/ut/integration/fixtures/kanban_tasks.jsonl
git commit -m "test(ut): verify Kanban mode (L4) with Worker isolation + scheduling loop"
```

---

## Self-Review

### 1. Spec Coverage

- ✅ Phase 1覆盖：Skills重命名（workflow→terminal-workflow, ut-test-collector→unit-test-collector）
- ✅ Phase 1覆盖：添加SOUL.md到4个Worker skills（batch-selector, unit-test-executor, failure-handler, manifest-updater）
- ✅ Phase 1覆盖：Stage1（unit-test-collector）不需要SOUL.md（由Supervisor直接执行）
- ✅ Phase 2覆盖：创建ut-batch-selector profile.yaml（Stage2）
- ✅ Phase 2覆盖：创建ut-manifest-updater profile.yaml（Stage5）
- ✅ Phase 2覆盖：更新deploy_tier.py（5个Worker profiles）
- ✅ Phase 3覆盖：dependency-resolver保持独立skill（不合并）
- ✅ Phase 3覆盖：创建kanban_task_creator.py（Kanban task创建）
- ✅ Phase 3覆盖：创建orchestrator_round.py（调度循环）
- ✅ Phase 4覆盖：测试Linear mode（L1-L3）
- ✅ Phase 4覆盖：测试Kanban mode（L4）

### 2. Placeholder Scan

- ✅ 无"TBD"、"TODO"、"implement later"
- ✅ 无"add appropriate error handling"等模糊描述
- ✅ 无"write tests for the above"（所有测试都有具体步骤）
- ✅ 无"similar to Task N"（每个Task独立完整）
- ✅ 无未定义的类型/函数引用

### 3. Type Consistency

- ✅ manifest_path: str 类型一致
- ✅ run_dir: str 类型一致
- ✅ kanban_file: str 类型一致
- ✅ task_name: str 类型一致
- ✅ Dict/List 类型标注一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-25-ut-skills-profiles-reorganization.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**