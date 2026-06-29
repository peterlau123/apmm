# UT Workflow配置管理与Batch合并设计

**日期：** 2026-06-29
**作者：** Claude
**状态：** Draft
**相关需求：**
- 需求1：配置文件管理（production环境分离）
- 需求2：merge_batch_manifests.py完善（更新策略）

---

## 问题陈述

### 需求1：配置文件管理

**现状问题：**
- `.agents/workflow.yaml` 配置散落，难以维护
- 生产测试和测试环境配置混杂
- 缺乏配置模板管理机制

**期望：**
- 生产测试使用 `deployment/production/` 配置
- 测试环境（l1~l4）使用 `tests/fixtures/` 配置
- terminal和飞书触发都通过交互确认选择环境
- 配置副本放置在 `runs/ut-xxx/` 目录（当前run实例）

### 需求2：merge_batch_manifests.py完善

**现状问题：**
- 只支持全量更新（所有test状态）
- 缺少"只更新passed"策略（重跑场景）

**期望：**
- 默认全量更新
- 参数切换：`--strategy passed-only`
- 输入：run文件夹 → 输出：更新run文件夹下的manifest.json
- 支持重跑场景：用户修复failed测试后，只记录passed结果

---

## 设计方案

### 需求1：配置文件管理

#### 1.1 架构设计

**环境识别：**

| 环境类型 | 配置位置 | 用途 |
|---------|---------|------|
| **测试环境** | `tests/ut/integration/fixtures/workflow.l{1,2,3,4}.yaml` | l1~l4测试（已存在） |
| **生产环境** | `tasks/ut/deployment/production/config/workflow.yaml` | 生产环境测试（用户维护） |

**配置流向：**

```
用户触发（terminal/飞书）
    ↓
SKILL.md交互节点（环境选择）
    ↓
用户确认（"测试环境l1~l4" 或 "生产环境"）
    ↓
┌──────────────────────────────────────┐
│ 测试环境 → tests/ut/integration/fixtures/ │ ← 已存在配置
│   ├── workflow.l1.yaml                │
│   ├── workflow.l2.yaml                │
│   ├── workflow.l3.yaml                │
│   └── workflow.l4.yaml                │
└──────────────────────────────────────┘
    或
┌──────────────────────────────────────┐
│ 生产环境 → deployment/production/     │ ← 用户维护模板
│   ├── config/workflow.yaml            │
│   └── profiles/{worker}/profile.yaml   │（可选）
└──────────────────────────────────────┘
    ↓
用户确认参数（batch_size, remote_server等）
    ↓
init_workflow_state.py（创建run目录）
    ↓
┌──────────────────────────────────────┐
│ runs/ut-{timestamp}/                  │ ← 运行实例（可修改）
│ ├── workflow.yaml                     │ ← 从模板复制+用户参数填充
│ ├── manifest.json                     │
│ ├── workflow_state.json               │
│ └── batches/                          │
└──────────────────────────────────────┘
    ↓
启动workflow（使用run目录下的workflow.yaml）
```

**关键原则：**
- **单向读取：** deployment/production是模板库（source of truth），runtime只读取不修改
- **配置副本：** 运行配置放置在 `runs/ut-xxx/workflow.yaml`
- **交互确认：** AI通过SKILL.md引导用户选择环境

#### 1.2 组件设计

**新增/修改组件：**

| 组件 | 类型 | 修改内容 |
|------|------|---------|
| `terminal-workflow SKILL.md` | 修改 | 添加"环境选择"交互节点 |
| `hermes-workflow SKILL.md` | 修改 | 添加"环境选择"交互节点 |
| `tasks/ut/scripts/load_deployment_config.py` | 新增 | 配置模板加载器 |
| `init_workflow_state.py` | 修改 | 增加 `--template-path` 参数 |

**SKILL.md交互节点示例：**

```markdown
## Stage 0: 环境选择（新增）

当用户触发"开始运行单元测试"：
- 提示：请选择运行环境：
  - 测试环境（l1~l4）：使用tests/fixtures配置
  - 生产环境：使用deployment/production配置
- 等待用户确认（"测试环境l1" / "测试环境l2" / ... / "生产环境"）
- 根据确认加载对应配置：
  - 测试环境：加载tests/ut/integration/fixtures/workflow.l{level}.yaml
  - 生产环境：加载tasks/ut/deployment/production/config/workflow.yaml
```

**配置加载器实现：**

```python
def load_deployment_config(env: str, level: int = None) -> Path:
    """Load workflow config from deployment or fixtures.

    Args:
        env: "production" or "test"
        level: 1-4 for test environment (l1~l4)

    Returns:
        Path to workflow.yaml template

    Raises:
        ValueError: Invalid env or level
    """
    if env == "production":
        template_path = Path("tasks/ut/deployment/production/config/workflow.yaml")
    elif env == "test":
        if level not in [1, 2, 3, 4]:
            raise ValueError("Test environment requires level 1-4")
        template_path = Path(f"tests/ut/integration/fixtures/workflow.l{level}.yaml")
    else:
        raise ValueError(f"Invalid env: {env}")

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    return template_path
```

#### 1.3 目录清理

**删除 `.agents/` 临时文件：**

```bash
# 删除废弃配置
rm .agents/workflow.yaml
rm .agents/workflow.l4.linear.yaml

# 删除临时文件
rm .agents/_resume_comment*.txt
rm -rf .agents/e2e_validation/
rm -rf .agents/logs/

# 删除测试环境配置目录
rm -rf tasks/ut/deployment/test/
```

**保留必要文件：**

```
.agents/
├── config.json          # Hermes系统配置
├── current_run.json     # 当前运行指针
├── feishu_config.json   # 飞书credentials
└── workflow/            # Hermes运行状态
```

**Deployment目录结构（简化）：**

```
tasks/ut/deployment/
└── production/               ← 只保留生产环境
    ├── config/
    │   └── workflow.yaml     ← 生产环境配置模板（用户维护）
    └── profiles/             ← Worker profiles（可选）
```

---

### 需求2：merge_batch_manifests.py完善

#### 2.1 参数设计

**新增参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--run-dir` | **必需** | Run目录路径（包含manifest.json和batches/） |
| `--strategy` | `all` | 更新策略：`all`（全量）或 `passed-only`（只更新passed） |
| `--output` | null | 可选输出路径（默认原地更新run_dir/manifest.json） |

**使用示例：**

```bash
# 全量更新（默认）
python tasks/ut/scripts/merge_batch_manifests.py \
    --run-dir runs/ut-20260629-123456

# 只更新passed（重跑场景）
python tasks/ut/scripts/merge_batch_manifests.py \
    --run-dir runs/ut-20260629-123456 \
    --strategy passed-only

# 输出到其他路径（可选）
python tasks/ut/scripts/merge_batch_manifests.py \
    --run-dir runs/ut-20260629-123456 \
    --output runs/ut-20260629-123456/manifest_final.json
```

#### 2.2 更新策略逻辑

**核心实现：**

```python
def merge_batch_results(manifest: dict, batch_results: dict, strategy: str = "all"):
    """Merge batch results with strategy control.

    Args:
        manifest: Input manifest dict
        batch_results: Batch execution results
        strategy: "all" (default) or "passed-only"

    Behavior:
        - all: Update all test statuses (passed, failed, error, retriable_error)
        - passed-only: Only update tests with status="passed",
                       keep failed/error tests unchanged (pending)

    Use case:
        - passed-only: User fixed failed tests and wants to rerun,
                       only record successful tests
    """
    tests = manifest.get("tests", [])
    by_id = {t.get("id"): t for t in tests}

    for result in batch_results.get("tests", []):
        target = by_id.get(result.get("id"))
        if target is None:
            continue

        new_status = result.get("status")

        # Strategy filter: passed-only skips non-passed tests
        if strategy == "passed-only" and new_status != "passed":
            continue

        # Update test status and metadata
        target["status"] = new_status
        target["last_batch_id"] = batch_results.get("batch_id")
        target["last_run_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Copy execution details
        if result.get("duration_ms"):
            target["last_duration_ms"] = result["duration_ms"]
        if result.get("exit_code"):
            target["last_exit_code"] = result["exit_code"]
        if result.get("log_path"):
            target["log_file"] = result["log_path"]

        # Update counters
        # run_count: 每次运行都+1（无论结果）
        target["run_count"] = int(target.get("run_count", 0)) + 1

        # retry_count: 第一次没pass后，后续所有运行都算retry
        # 约束：同一次run中，passed后test固化，不会再retry
        prev_status = target.get("status", "pending")
        has_failed_before = prev_status in ("failed", "retriable_error", "error")

        if has_failed_before:
            # 曾经失败过，这次运行算retry
            target["retry_count"] = int(target.get("retry_count", 0)) + 1
        elif new_status in ("failed", "retriable_error", "error"):
            # 第一次失败，不算retry（还未重试）
            pass  # retry_count保持不变
```

**计数器语义：**

| 计数器 | 语义 | 更新时机 |
|--------|------|---------|
| **run_count** | 总运行次数（当前run内） | 每次运行都+1 |
| **retry_count** | 第一次没pass后的重试次数 | 曾经失败后的所有运行都+1 |

**场景验证（单次run）：**

| 执行顺序 | prev_status | new_status | run_count | retry_count | 说明 |
|---------|-------------|------------|-----------|-------------|------|
| 第1次执行 | pending | failed | 1 | 0 | 首次失败，不算retry |
| 第2次执行 | failed | failed | 2 | 1 | 曾经失败，算retry |
| 第3次执行 | failed | passed | 3 | 2 | 曾经失败，算retry（固化） |

#### 2.3 Run目录自动发现

**自动化逻辑：**

```python
def discover_run_files(run_dir: Path) -> tuple[Path, list[Path]]:
    """Auto-discover manifest and batches in run directory.

    Returns:
        (manifest_path, batch_dirs)

    Raises:
        FileNotFoundError: No manifest.json or batches/ in run_dir
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")

    batches_dir = run_dir / "batches"
    if not batches_dir.exists():
        raise FileNotFoundError(f"batches/ not found: {batches_dir}")

    batch_dirs = []
    for batch_dir in sorted(batches_dir.iterdir()):
        if batch_dir.is_dir() and (batch_dir / "batch_results.json").exists():
            batch_dirs.append(batch_dir)

    return manifest_path, batch_dirs
```

**简化调用：**

```python
# 用户只需提供run_dir，无需手动指定manifest和batches
run_dir = Path("runs/ut-20260629-123456")
manifest_path, batch_dirs = discover_run_files(run_dir)
manifest = load_manifest(manifest_path)

for batch_dir in batch_dirs:
    batch_results = load_batch_results(batch_dir / "batch_results.json")
    manifest = merge_batch_results(manifest, batch_results, strategy="passed-only")

# 默认原地更新（backup=true）
save_manifest(manifest, manifest_path, backup=True)
```

#### 2.4 错误处理

| 场景 | 处理方式 |
|------|---------|
| run_dir不存在 | ❌ 报错退出 |
| manifest.json缺失 | ❌ 报错退出 |
| batches/缺失 | ❌ 报错退出 |
| batch_results.json缺失 | ⚠️ 跳过该batch（警告日志） |
| batch中test_id不在manifest中 | ⚠️ 跳过该test（警告日志） |
| strategy参数非法 | ❌ 报错退出（只允许"all"或"passed-only"） |

---

## 实现要点

### 需求1实现要点

1. **修改SKILL.md：**
   - terminal-workflow SKILL.md添加Stage 0交互节点
   - hermes-workflow SKILL.md修改飞书命令解析逻辑

2. **新增配置加载器：**
   - `tasks/ut/scripts/load_deployment_config.py`
   - 支持production和test环境加载

3. **修改init_workflow_state.py：**
   - 增加 `--template-path` 参数
   - 实现模板复制到run目录逻辑

4. **清理.agents目录：**
   - 删除废弃配置和临时文件
   - 保留必要系统文件

5. **删除test环境目录：**
   - `rm -rf tasks/ut/deployment/test/`

### 需求2实现要点

1. **修改merge_batch_manifests.py参数：**
   - 移除 `--input`（改为自动发现）
   - 新增 `--strategy`（默认all）
   - `--run-dir`变为必需参数

2. **实现策略逻辑：**
   - passed-only：跳过非passed状态的test
   - 更新计数器逻辑（run_count/retry_count）

3. **实现自动发现：**
   - discover_run_files函数
   - 默认原地更新manifest.json

4. **添加错误处理：**
   - 参数验证
   - 文件缺失检查
   - 日志警告

---

## 测试验证

### 需求1测试场景

1. **terminal触发测试环境：**
   - 用户："开始运行单元测试"
   - AI："请选择测试环境l1~l4或生产环境"
   - 用户："测试环境l2"
   - 验证：加载tests/fixtures/workflow.l2.yaml → 复制到runs/ut-xxx/workflow.yaml

2. **飞书触发生产环境：**
   - 用户飞书："单元测试"
   - AI："请选择测试环境l1~l4或生产环境"
   - 用户："生产环境"
   - 验证：加载deployment/production/workflow.yaml → 复制到runs/ut-xxx/workflow.yaml

### 需求2测试场景

1. **全量更新（默认）：**
   - 输入：run_dir包含3个batch（passed/failed/error混合）
   - 输出：manifest.json更新所有test状态
   - 验证：passed、failed、error都被更新

2. **passed-only策略：**
   - 输入：run_dir包含3个batch（passed/failed/error混合）
   - 输出：manifest.json只更新passed的test
   - 验证：failed/error保持pending状态

3. **计数器验证：**
   - failed → failed → passed（3次执行）
   - 验证：run_count=3, retry_count=2

---

## 风险与缓解

### 需求1风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| production配置缺失 | 生产测试无法启动 | 提供配置模板文档，用户初始化时生成 |
| SKILL.md交互逻辑复杂 | 用户困惑 | 简化提示文案，提供默认选项 |
| 配置模板路径硬编码 | 迁移困难 | 使用PROJECT_ROOT动态定位 |

### 需求2风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| passed-only误用 | 忽略失败测试，数据不完整 | 文档明确使用场景（重跑） |
| manifest原地更新丢失历史 | 无法追溯 | 自动备份（manifest_backup_timestamp.json） |
| 计数器逻辑误解 | 统计不准确 | 文档明确语义，添加unit test验证 |

---

## 部署影响

### 需求1部署影响

1. **`.agents/` 清理：**
   - 现有 `.agents/workflow.yaml` 废弃
   - 需要用户确认删除临时文件

2. **deployment目录简化：**
   - 删除 `tasks/ut/deployment/test/`
   - production目录作为唯一模板库

3. **workflow启动流程变更：**
   - 从单路径配置 → 双路径选择
   - 需要更新文档和用户指南

### 需求2部署影响

1. **merge_batch_manifests.py向后兼容：**
   - 移除 `--input` 参数（改为自动发现）
   - 需要更新现有调用脚本

2. **计数器语义变更：**
   - retry_count定义更精确
   - 需要文档说明变更

---

## 后续优化

1. **Deployment模板版本管理：**
   - 暂不实现（用户手动维护）
   - 未来可考虑版本化模板库

2. **配置参数智能填充：**
   - 用户确认环境后，AI引导填写关键参数
   - 减少用户手动编辑配置文件

3. **merge_batch_manifests.py可视化：**
   - 生成merge报告（差异摘要）
   - 飞书通知merge结果

---

## 相关文档

- `tasks/ut/docs/guides/testing.md` - 测试环境使用指南
- `skills/ut/terminal-workflow/SKILL.md` - Terminal workflow交互流程
- `skills/ut/hermes-workflow/SKILL.md` - Hermes workflow飞书命令解析
- `tasks/ut/scripts/merge_batch_manifests.py` - Batch合并脚本（现有）

---

**Co-Authored-By: Claude <noreply@anthropic.com>**