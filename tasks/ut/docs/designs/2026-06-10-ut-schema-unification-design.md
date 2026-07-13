# UT Workflow JSON Schema 统一设计

> **日期**: 2026-06-10
> **状态**: 设计完成，待实施
> **背景**: UT Workflow 各 Stage 产出的 JSON 文件存在字段不一致、与 schema 不匹配的问题
> **注意：** `.agents/workflow.yaml`已废弃（2026-06-29），配置机制已迁移至`tasks/ut/deployment/production/config/`模板库 + `runs/ut-{timestamp}/`副本机制。

---

## 问题诊断

### 1. manifest.json 与 schema 不匹配

| 问题类型 | 详情 |
|----------|------|
| 字段名不一致 | `test_func` vs `test_name`, `run_at` vs `last_run_at` |
| 缺失字段 | 缺少 `version`, `source` (schema required) |
| enum 不匹配 | `error_type` 使用单字母编码 (M/A/B/C/D/E)，schema 定义为描述性字符串 |
| 未定义字段 | `phase`, `source_files` 在数据中存在但 schema 未定义 |

### 2. Stage 间数据流问题

- `batch_results.json` 生成脚本只启动 pytest，不解析结果
- 各 Stage 间 `test_node` 字段传递一致，但命名需统一

### 3. 缺少 schema 校验机制

所有脚本输出 JSON 前缺少 schema 验证，可能产生无效数据。

---

## 设计决策

### 决策表

| 决策点 | 选择 | 理由 |
|--------|------|------|
| manifest.json 处理 | 复制备份 → 新建 | 保留历史数据，不影响现有记录 |
| `test_func` → `test_name` | 统一重命名 | 符合 schema 定义 |
| `run_at` → `last_run_at` | 统一重命名 | 符合 schema 定义 |
| `phase` 字段 | 移除 | 简化数据结构 |
| `source_files` 字段 | 移除 | 简化数据结构 |
| error_type 映射 | 单字母 → 描述性字符串 | 符合 schema enum |
| Schema 存放位置 | 单 skill → skill 目录，多 skill 共用 → shared | 责任清晰 |
| 校验脚本组织 | 单一通用脚本 `validate_schema.py` | 统一维护 |
| 校验时机 | 写入前校验 | 防止无效数据写入磁盘 |
| 实施方案 | 分阶段实施 (Phase 1-4) | 风险可控，逐步验证 |

---

## 校验时机说明

### workflow.yaml 校验时机

| 时机 | 位置 | 校验失败处理 |
|------|------|-------------|
| **Supervisor 启动前** | `supervisor_loop.py` 或 `init_workflow_state.py` | 停止启动 Workflow，输出错误信息 |

**校验流程**:

```python
# supervisor_loop.py 启动前
from shared.validate_schema import validate_yaml

# 校验 workflow.yaml
workflow_yaml_path = Path(".agents/workflow.yaml")
is_valid, errors = validate_yaml(workflow_yaml_path, "workflow")

if not is_valid:
    print(f"[ERROR] workflow.yaml 校验失败，Workflow 无法启动:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)  # 停止启动

# 校验通过后继续启动 Supervisor
print("[OK] workflow.yaml 校验通过，启动 Workflow...")
```

### 其他 JSON 校验时机

| JSON 文件 | 校验时机 | 校验失败处理 |
|-----------|----------|-------------|
| workflow_state.json | `init_workflow_state.py` 输出前 | 不写入，返回错误 |
| batch_config.json | `generate_batch.py` 输出前 | 不写入，返回错误给 Supervisor |
| batch_results.json | `run_batch.py` 输出前 | 不写入，返回错误给 Supervisor |
| handled_tests.json | `generate_handled_manifest.py` 输出前 | 不写入，返回错误给 Supervisor |
| manifest.json | `update_test_load.py` 输出前 | 不写入，返回错误给 Supervisor |

---

## Schema 目录分配

```
skills/ut/
├── batch-selector/
│   └── batch_config_schema.json     ← Stage 2 产出（单 skill）
│
├── unit-test-executor/
│   └── batch_results_schema.json    ← Stage 3 产出（单 skill）
│
├── failure-handler/
│   └── handled_tests_schema.json    ← Stage 4 产出（单 skill）
│
├── supervisor/
│   └── workflow_state_schema.json   ← Supervisor 产出（单 skill）
│   └── workflow_schema.yaml         ← Workflow YAML schema（单 skill）
│
├── shared/
│   ├── manifest_schema.json         ← Stage 1 创建 + Stage 5 更新（多 skill 共用）
│   └── validate_schema.py           ← 通用校验脚本（支持 JSON 和 YAML）
│   └── migrate_manifest.py          ← 迁移脚本
```

---

## 枚举字段注释定义

### delegate_to (执行 Agent 类型)

| 值 | 说明 |
|----|------|
| `claude-code` | Claude Code CLI Agent（Anthropic） |
| `opencode` | OpenCode Agent（OpenAI） |
| `codex` | Codex Agent（GitHub） |
| `self` | 当前 Agent 自己执行，不委托给其他 Agent |

### kanban.action (Kanban 操作类型)

| 值 | 说明 |
|----|------|
| `create_board` | 创建 Kanban 看板 |
| `create_lane` | 创建泳道（批次执行时） |
| `update_lane` | 更新泳道进度 |
| `move_lane` | 移动泳道到目标状态 |

### status / status_mapping (测试状态)

| 值 | 说明 |
|----|------|
| `pending` | 待执行 |
| `running` | 正在执行 |
| `passed` | 测试通过 |
| `failed` | 断言失败（AssertionError） |
| `error` | 执行错误（Collection/Import/Download） |
| `ignored` | 已忽略（不执行） |

### next_action (Worker 下一步动作)

| 值 | 说明 |
|----|------|
| `continue` | 继续执行下一 Stage |
| `pause` | 暂停 Workflow，等待人工介入 |
| `stop` | 停止 Workflow，不再继续 |
| `wait` | 等待资源释放后继续 |

### break_conditions.action (条件触发动作)

| 值 | 说明 |
|----|------|
| `pause` | 暂停 Workflow，发送通知 |
| `stop` | 停止 Workflow，不再继续 |

### error_type (错误类型分类)

| 值 | 说明 | 常见场景 |
|----|------|----------|
| `dependency` | 依赖缺失 | ImportError, ModuleNotFoundError |
| `network` | 网络错误 | ConnectionError, HTTP 503/404 |
| `resource` | 资源不足 | CUDA OOM, GPU 不可用 |
| `version` | 版本兼容问题 | vLLM v0.13.0 + PyTorch 2.5.1 兼容性 |
| `functional` | 功能错误 | AssertionError, ValueError |
| `download_error` | 模型下载失败 | Model not found, config.json missing |
| `other` | 其他错误 | 未分类的错误类型 |

---

## Schema 文件注释要求

所有 schema 文件需要在 enum 字段添加注释，格式如下：

```json
{
  "status": {
    "type": "string",
    "description": "测试状态",
    "enum": ["pending", "running", "passed", "failed", "error", "ignored"],
    "_enum_comments": {
      "pending": "待执行",
      "running": "正在执行",
      "passed": "测试通过",
      "failed": "断言失败（AssertionError）",
      "error": "执行错误（Collection/Import/Download）",
      "ignored": "已忽略（不执行）"
    }
  }
}
```

> **注意**: `_enum_comments` 是自定义字段，用于文档说明，不影响 JSON Schema 校验。

---

## 字段迁移映射表

### manifest.json 测试项字段

| 原字段 | 新字段 | 处理方式 |
|--------|--------|----------|
| `test_func` | `test_name` | 直接重命名 |
| `run_at` | `last_run_at` | 直接重命名 |
| `phase` | - | 移除 |
| `error_type: "M"` | `error_type: "download_error"` | 值映射 |
| `error_type: "A"` | `error_type: "dependency"` | 值映射 |
| `error_type: "B"` | `error_type: "network"` | 值映射 |
| `error_type: "C"` | `error_type: "resource"` | 值映射 |
| `error_type: "D"` | `error_type: "version"` | 值映射 |
| `error_type: "E"` | `error_type: "functional"` | 值映射 |
| `error_type: null` | `error_type: null` | 保持 null |
| `error_type: 其他值` | `error_type: "other"` | 兜底映射 |

### manifest.json 文件级字段

| 原字段 | 新字段 | 处理方式 |
|--------|--------|----------|
| `source_files` | - | 移除 |
| - | `version` | 新增，默认 "2.0" |
| - | `source` | 新增，默认 "pytest_collect" |

---

## 实施计划

### Phase 1: Schema 更新

**目标**: 更新所有 schema 文件，统一字段定义

**任务清单**:
- [ ] 1.1 移动 schema 文件到新目录结构
  - `batch_config_schema.json` → `skills/ut/batch-selector/`
  - `batch_results_schema.json` → `skills/ut/unit-test-executor/`
  - `handled_tests_schema.json` → `skills/ut/failure-handler/`
  - `workflow_state_schema.json` → `skills/ut/terminal-workflow/`
  - `manifest_schema.json` → 保持在 `skills/ut/shared/`

- [ ] 1.2 创建 `workflow_schema.yaml`（YAML 格式 schema）
  - 位置: `skills/ut/terminal-workflow/workflow_schema.yaml`
  - 内容: 定义 workflow.yaml 的结构和约束
  - 枚举字段添加 `_enum_comments` 注释

- [ ] 1.3 更新 `manifest_schema.json`
  - 确认 `test_name` 字段（替代 `test_func`）
  - 确认 `last_run_at` 字段（替代 `run_at`）
  - 不添加 `phase`、`source_files` 字段
  - 枚举字段添加 `_enum_comments` 注释

- [ ] 1.4 更新其他 schema 文件添加枚举注释
  - `workflow_state_schema.json` - current_stage, next_action, status
  - `batch_results_schema.json` - status, error_type
  - `handled_tests_schema.json` - final_status, error_type, action, ignored_reason
  - `batch_config_schema.json` - tests[].status

**验证方式**: 使用 `jsonschema` 库对现有数据进行校验测试

---

### Phase 2: 校验脚本

**目标**: 创建通用 schema 校验脚本

**文件**: `skills/ut/shared/validate_schema.py`

**核心函数**:

```python
def validate_json(data: dict, schema_name: str) -> tuple[bool, list[str]]:
    """
    校验 JSON 数据是否符合对应 schema

    Args:
        data: 待校验的 JSON 数据
        schema_name: schema 名称
          ("manifest", "batch_config", "batch_results", "handled_tests", "workflow_state", "workflow")

    Returns:
        (is_valid, errors): 是否通过，错误列表
    """

def validate_yaml(yaml_path: Path, schema_name: str) -> tuple[bool, list[str]]:
    """
    校验 YAML 文件是否符合对应 schema

    Args:
        yaml_path: YAML 文件路径
        schema_name: schema 名称（如 "workflow")

    Returns:
        (is_valid, errors): 是否通过，错误列表
    """

def validate_and_write(data: dict, schema_name: str, output_path: Path) -> tuple[bool, list[str]]:
    """
    校验后写入文件（写入前校验）

    Args:
        data: 待校验和写入的数据
        schema_name: schema 名称
        output_path: 输出文件路径

    Returns:
        (is_valid, errors): 是否成功写入，错误列表

    Behavior:
        - 校验失败时不写入文件
        - 返回详细错误信息
    """
```

**Schema 文件映射**:

```python
SCHEMA_FILES = {
    "batch_config": "skills/ut/batch-selector/batch_config_schema.json",
    "batch_results": "skills/ut/unit-test-executor/batch_results_schema.json",
    "handled_tests": "skills/ut/failure-handler/handled_tests_schema.json",
    "manifest": "skills/ut/shared/manifest_schema.json",
    "workflow_state": "skills/ut/terminal-workflow/workflow_state_schema.json",
    "workflow": "skills/ut/terminal-workflow/workflow_schema.yaml",  # YAML schema
}
```

**任务清单**:
- [ ] 2.1 创建 `validate_schema.py`
- [ ] 2.2 实现 `validate_json()` 函数
- [ ] 2.3 实现 `validate_yaml()` 函数（支持 workflow.yaml 校验）
- [ ] 2.4 实现 `validate_and_write()` 函数
- [ ] 2.5 添加 CLI 支持（可单独运行校验）

**验证方式**: 对现有 JSON/YAML 文件进行校验测试

---

### Phase 3: 迁移脚本

**目标**: 将现有 manifest.json 迁移到新 schema 格式

**文件**: `skills/ut/shared/migrate_manifest.py`

**核心函数**:

```python
ERROR_TYPE_MAP = {
    "M": "download_error",
    "A": "dependency",
    "B": "network",
    "C": "resource",
    "D": "version",
    "E": "functional",
}

def migrate_test_item(test: dict) -> dict:
    """
    单个测试项迁移

    字段映射:
    - test_func → test_name
    - run_at → last_run_at
    - error_type: M/A/B/C/D/E → download_error/dependency/network/resource/version/functional
    - error_type: 其他 → other
    - 移除 phase 字段
    """

def migrate_manifest(source_path: Path, target_path: Path, backup: bool = True) -> dict:
    """
    迁移 manifest.json 到新 schema 格式

    Args:
        source_path: 原 manifest.json 路径
        target_path: 目标路径（新格式）
        backup: 是否创建备份 (manifest_legacy.json)

    Returns:
        迁移结果统计
    """
```

**任务清单**:
- [ ] 3.1 创建 `migrate_manifest.py`
- [ ] 3.2 实现 `migrate_test_item()` 函数
- [ ] 3.3 实现 `migrate_manifest()` 函数
- [ ] 3.4 执行迁移：`tasks/ut/test_analysis/manifest.json` → `manifest_legacy.json` + 新 `manifest.json`
- [ ] 3.5 校验新 manifest.json 符合 schema

**验证方式**: 迁移后使用 `validate_schema.py` 校验新文件

---

### Phase 4: 脚本集成校验

**目标**: 在所有 JSON/YAML 相关脚本中集成 schema 校验

**需要修改的脚本**:

| 脚本 | 校验内容 | 校验时机 |
|------|----------|----------|
| `supervisor/scripts/supervisor_loop.py` | workflow.yaml | **启动前校验**，失败则停止启动 |
| `supervisor/scripts/init_workflow_state.py` | workflow_state.json | 输出前校验 |
| `batch-selector/scripts/generate_batch.py` | batch_config.json | 输出前校验 |
| `unit-test-executor/scripts/run_batch.py` | batch_results.json | 输出前校验 |
| `failure-handler/scripts/generate_handled_manifest.py` | handled_tests.json | 输出前校验 |
| `manifest-updater/scripts/update_test_load.py` | manifest.json | 输出前校验 |

**修改示例 (JSON 输出)**:

```python
# 原来的写入逻辑
# output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

# 改为校验后写入
from shared.validate_schema import validate_and_write

is_valid, errors = validate_and_write(data, schema_name, output_path)
if not is_valid:
    return {"error": "schema_validation_failed", "details": errors}
```

**修改示例 (YAML 启动前校验)**:

```python
# supervisor_loop.py 启动前
from shared.validate_schema import validate_yaml

workflow_yaml_path = Path(".agents/workflow.yaml")
is_valid, errors = validate_yaml(workflow_yaml_path, "workflow")

if not is_valid:
    print(f"[ERROR] workflow.yaml 校验失败，Workflow 无法启动:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)  # 停止启动

print("[OK] workflow.yaml 校验通过，启动 Workflow...")
```

**任务清单**:
- [ ] 4.1 修改 `supervisor_loop.py` 添加 workflow.yaml 启动前校验
- [ ] 4.2 修改 `init_workflow_state.py` 添加 workflow_state.json 校验
- [ ] 4.3 修改 `generate_batch.py` 添加 batch_config.json 校验
- [ ] 4.4 修改 `run_batch.py` 添加 batch_results.json 校验
- [ ] 4.5 修改 `generate_handled_manifest.py` 添加 handled_tests.json 校验
- [ ] 4.6 修改 `update_test_load.py` 添加 manifest.json 校验
- [ ] 4.7 验证所有脚本校验逻辑正确

**验证方式**: 运行各脚本，检查校验逻辑正确触发

---

## 验收标准

| Phase | 验收标准 |
|-------|----------|
| 1 | 所有 schema 文件位于正确目录，枚举字段添加 `_enum_comments` 注释 |
| 2 | `validate_schema.py` 可校验 JSON 和 YAML（workflow.yaml）文件 |
| 3 | 新 `manifest.json` 校验通过，备份文件 `manifest_legacy.json` 存在 |
| 4 | Supervisor 启动前校验 workflow.yaml；所有脚本输出前校验，校验失败不写入 |

---

## 遗留 TODO

已在 `tasks/ut/todo.md` 记录：

- [ ] 设计 pytest 结果解析逻辑（batch_results.json 生成）
- [ ] 添加 schema 校验到所有 JSON 生成脚本（本次 Phase 4）

---

## 相关文件

| 文件 | 路径 |
|------|------|
| UT Workflow README | `tasks/ut/README.md` |
| UT TODO | `tasks/ut/todo.md` |
| Workflow YAML | `.agents/workflow.yaml` |
| manifest.json | `tasks/ut/test_analysis/manifest.json` |