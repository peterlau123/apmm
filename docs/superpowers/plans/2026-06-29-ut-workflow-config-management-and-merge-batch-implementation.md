# UT Workflow配置管理与Batch合并实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现UT workflow配置管理（production/test环境分离）和merge_batch_manifests.py完善（更新策略参数化）

**Architecture:** 
- 配置管理：deployment/production作为模板库 → terminal/飞书交互确认 → 配置副本到runs/ut-xxx/
- merge_batch_manifests：参数化策略（--strategy all|passed-only）+ 自动发现 + 计数器语义澄清

**Tech Stack:** Python 3.10+, Path manipulation, YAML parsing, argparse

---

## File Structure

**需求1：配置文件管理**

| 文件 | 操作 | 负责 |
|------|------|------|
| `skills/ut/terminal-workflow/SKILL.md` | 修改 | 添加Stage 0环境选择交互节点 |
| `skills/ut/hermes-workflow/SKILL.md` | 修改 | 添加飞书命令环境选择解析 |
| `tasks/ut/scripts/load_deployment_config.py` | 新增 | 配置模板加载器（production/test） |
| `skills/ut/terminal-workflow/scripts/init_workflow_state.py` | 修改 | 增加--template-path参数，实现模板复制 |
| `.agents/workflow.yaml` | 删除 | 废弃配置（改为runs/ut-xxx/workflow.yaml） |
| `.agents/workflow.l4.linear.yaml` | 删除 | 已commit的配置副本 |
| `.agents/_resume_comment*.txt` | 删除 | 临时文件（3个） |
| `.agents/e2e_validation/` | 删除目录 | 临时验证数据 |
| `.agents/logs/` | 删除目录 | 旧日志（日志应在run目录） |
| `tasks/ut/deployment/test/` | 删除目录 | 测试环境配置（改为tests/fixtures） |

**需求2：merge_batch_manifests.py完善**

| 文件 | 操作 | 负责 |
|------|------|------|
| `tasks/ut/scripts/merge_batch_manifests.py` | 修改 | 参数化策略、自动发现、计数器逻辑 |
| `tests/ut/unit/test_merge_batch_manifests_strategy.py` | 新增 | 策略逻辑测试（passed-only） |
| `tests/ut/unit/test_merge_batch_manifests_discovery.py` | 新增 | 自动发现测试 |

---

## Task 1: 新增配置加载器

**Files:**
- Create: `tasks/ut/scripts/load_deployment_config.py`
- Test: `tests/ut/unit/test_load_deployment_config.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for load_deployment_config.py"""
import pytest
from pathlib import Path

def test_load_production_config():
    """Production environment config path resolved correctly."""
    from tasks.ut.scripts.load_deployment_config import load_deployment_config
    result = load_deployment_config(env="production")
    expected = Path("tasks/ut/deployment/production/config/workflow.yaml")
    assert result == expected

def test_load_test_config_l2():
    """Test environment l2 config path resolved correctly."""
    from tasks.ut.scripts.load_deployment_config import load_deployment_config
    result = load_deployment_config(env="test", level=2)
    expected = Path("tests/ut/integration/fixtures/workflow.l2.yaml")
    assert result == expected

def test_load_test_config_invalid_level():
    """Test environment with invalid level raises ValueError."""
    from tasks.ut.scripts.load_deployment_config import load_deployment_config
    with pytest.raises(ValueError) as exc_info:
        load_deployment_config(env="test", level=5)
    assert "level 1-4" in str(exc_info.value)

def test_load_invalid_env():
    """Invalid env raises ValueError."""
    from tasks.ut.scripts.load_deployment_config import load_deployment_config
    with pytest.raises(ValueError) as exc_info:
        load_deployment_config(env="staging")
    assert "Invalid env" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ut/unit/test_load_deployment_config.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
"""load_deployment_config.py - Load workflow config from deployment or fixtures."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def load_deployment_config(env: str, level: int | None = None) -> Path:
    """Load workflow config from deployment or fixtures.
    
    Args:
        env: "production" or "test"
        level: 1-4 for test environment (l1~l4)
    
    Returns:
        Path to workflow.yaml template
    
    Raises:
        ValueError: Invalid env or level
        FileNotFoundError: Template not found
    """
    if env == "production":
        template_path = PROJECT_ROOT / "tasks/ut/deployment/production/config/workflow.yaml"
    elif env == "test":
        if level not in [1, 2, 3, 4]:
            raise ValueError(f"Test environment requires level 1-4, got: {level}")
        template_path = PROJECT_ROOT / f"tests/ut/integration/fixtures/workflow.l{level}.yaml"
    else:
        raise ValueError(f"Invalid env: {env}. Must be 'production' or 'test'")
    
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    
    return template_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ut/unit/test_load_deployment_config.py -v`
Expected: PASS (if production template exists)

- [ ] **Step 5: Commit**

```bash
git add tasks/ut/scripts/load_deployment_config.py tests/ut/unit/test_load_deployment_config.py
git commit -m "feat(ut): add load_deployment_config for environment-based template loading

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 修改terminal-workflow SKILL.md添加环境选择

**Files:**
- Modify: `skills/ut/terminal-workflow/SKILL.md`

- [ ] **Step 1: Add Stage 0 interaction node**

在SKILL.md开头添加：

```markdown
## Stage 0: 环境选择（新增）

当用户触发"开始运行单元测试"：

**AI行为：**
1. 提示用户选择运行环境：
   ```
   请选择运行环境：
   - 测试环境（l1~l4）
   - 生产环境
   请回复："测试环境l1" 或 "生产环境"
   ```

2. 等待用户确认

3. 根据确认调用load_deployment_config：
   - 测试环境：load_deployment_config("test", level=2)
   - 生产环境：load_deployment_config("production")

4. 复制模板到runs/ut-{timestamp}/workflow.yaml

**相关文档：**
- tasks/ut/docs/designs/2026-06-29-ut-workflow-config-management-and-merge-batch-design.md
```

- [ ] **Step 2: Commit**

```bash
git add skills/ut/terminal-workflow/SKILL.md
git commit -m "feat(ut): add Stage 0 environment selection in terminal-workflow SKILL.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3-6: 配置管理剩余任务（批量执行）

**Files:**
- Modify: `skills/ut/hermes-workflow/SKILL.md`
- Modify: `skills/ut/terminal-workflow/scripts/init_workflow_state.py`
- Delete: `.agents/` 临时文件和目录
- Delete: `tasks/ut/deployment/test/`

- [ ] **Step 1: hermes-workflow SKILL.md**

添加飞书环境选择解析（同Task 2逻辑）

- [ ] **Step 2: init_workflow_state.py**

添加--template-path参数和模板复制逻辑

- [ ] **Step 3: .agents清理**

```bash
rm .agents/workflow.yaml .agents/workflow.l4.linear.yaml
rm .agents/_resume_comment*.txt
rm -rf .agents/e2e_validation/ .agents/logs/
```

- [ ] **Step 4: deployment/test删除**

```bash
rm -rf tasks/ut/deployment/test/
```

- [ ] **Step 5: Commit all**

```bash
git add skills/ut/hermes-workflow/SKILL.md skills/ut/terminal-workflow/scripts/init_workflow_state.py .agents/ tasks/ut/deployment/
git commit -m "feat(ut): complete config management tasks - hermes SKILL, init_workflow_state, .agents cleanup

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7-11: merge_batch_manifests完善（批量执行）

**Files:**
- Modify: `tasks/ut/scripts/merge_batch_manifests.py`
- Create: `tests/ut/unit/test_merge_batch_manifests_strategy.py`
- Create: `tests/ut/unit/test_merge_batch_manifests_discovery.py`

- [ ] **Step 1: 参数修改**

添加--strategy参数（all|passed-only）

- [ ] **Step 2: 策略逻辑**

实现passed-only过滤和计数器逻辑

- [ ] **Step 3: 自动发现**

实现discover_run_files函数

- [ ] **Step 4: 测试编写**

创建strategy和discovery测试文件

- [ ] **Step 5: Commit**

```bash
git add tasks/ut/scripts/merge_batch_manifests.py tests/ut/unit/test_merge_batch_manifests*.py
git commit -m "feat(ut): complete merge_batch_manifests enhancement - strategy, discovery, tests

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

**实施计划完成。推荐使用Subagent-Driven执行。**