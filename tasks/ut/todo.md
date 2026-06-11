# UT Workflow TODO List

> 记录待完成的设计和实现任务

---

## 2026-06-11: 文件整理与文档优化

### TODO

- [x] **UT Workflow 过滤规则汇聚** - P1 ✅ 2026-06-11 已完成
  - 背景: 过滤规则分散在 7+ 个位置，需建立单一来源
  - 设计文档: [2026-06-11-ut-filter-rules-consolidation-design.md](../../docs/superpowers/specs/2026-06-11-ut-filter-rules-consolidation-design.md)
  - 实施:
    1. ✅ 创建 `skills/ut/shared/filter_rules.yaml`（41条规则）
    2. ✅ 创建 `skills/ut/shared/load_filter_rules.py`（5个函数）
    3. ✅ 精简 `pytest_config.py`（移除37条规则）
    4. ✅ 更新 `workflow.yaml`（添加 input_filter 块）
    5. ✅ 更新 `generate_batch.py`（使用 load_filter_rules）
  - Commit: 8557b48

- [x] **tasks/ut/ 文件清理** - P1 ✅ 2026-06-11 已完成
  - 背景: 目录中存在42个可删除的冗余/过时/已迁移文件
  - 结果: 检查发现大部分文件已不存在（之前已清理）
  - 保留: docs/reports/ 目录保留（compatibility、weekly、test-summary.md）
  - 依赖: 无

- [x] **PROGRESS.md 与 WORKLOG.md 整理** - P1 ✅ 2026-06-11 已完成
  - 背景: 两个文件内容混杂，缺乏标准化更新模板
  - 结果: 检查发现已按模板整理（PROGRESS.md 152行，WORKLOG.md 75行）
  - 职责分工已明确: PROGRESS.md = 统计/架构/兼容性；WORKLOG.md = 每日任务/测试执行
  - 依赖: 无

---

## 文件清理清单

### 可删除文件（42个）

| 分类 | 文件数 | 典型文件 |
|------|:------:|----------|
| **A. 已迁移脚本** | 16 | `scripts/merge_manifests.py`, `scripts/update_status.py` |
| **B. Archive备份** | 5 | `test_analysis/archive/phase1_manifest_*.json` |
| **C. 过时状态文件** | 4 | `execution_state.json`, `state_manager.py` |
| **D. 测试脚本残留** | 4 | `scripts/test_automation_unit_tests.py`, `conftest.py` |
| **E. 过时数据文件** | 6 | `test_analysis/test_lists_marked/*` |
| **F. 过时报告** | 7 | `docs/reports/error-analysis.md` |

### 保留文件（15个）

| 文件 | 职责 |
|------|------|
| `README.md` | 主入口文档 |
| `PROGRESS.md` | 进度追踪 |
| `GOAL.md` | 测试目标 |
| `WORKLOG.md` | 工作日志 |
| `todo.md` | 待办事项 |
| `test_analysis/manifest.json` | **核心数据** |
| `docs/guides/*.md` | 操作指南 |

---

## 进度整理方案

### 当前问题

| 问题 | 影响 |
|------|------|
| PROGRESS.md过长（774行） | 难以快速查看关键进度 |
| WORKLOG.md与PROGRESS.md内容重复 | 信息冗余 |
| 缺乏标准化更新模板 | 每次更新格式不一致 |
| 统计数据分散 | 需要翻阅多个章节 |

### 建议方案

**职责分工**：

| 文件 | 职责 | 内容 |
|------|------|------|
| **PROGRESS.md** | 进度追踪 | 统计数据、架构设计、兼容性汇总 |
| **WORKLOG.md** | 工作记录 | 每日任务、测试执行、问题修复 |

**PROGRESS.md更新模板**：

```markdown
<!-- STATS_UPDATE_{TIMESTAMP} -->
### 📊 最新统计 ({DATE})

| 指标 | 数值 |
|------|------|
| 总测试用例数 | {TOTAL} |
| 已执行用例数 | {EXECUTED} |
| 进度 | {PROGRESS}% |
| 通过数 | {PASSED} |
| 失败数 | {FAILED} |
| 错误数 | {ERROR} |
| 待执行数 | {PENDING} |

<!-- END_STATS_UPDATE -->
```

**WORKLOG.md更新模板**：

```markdown
## {DATE}

### 完成任务
- [时间] 任务描述

### 测试执行
| 目录/文件 | 通过 | 失败 | 错误 | 说明 |
|-----------|:----:|:----:|:----:|------|

### 遇到问题
- [问题描述] → [解决方案/状态]

### 修复记录
| 文件 | 修复内容 | PR/Commit |
|------|----------|-----------|
```

---

## 2026-06-10: Schema 统一与校验设计 ✅ 已完成

### 背景

在进行 UT Workflow JSON schema 统一设计时，发现 `batch_results.json` 的生成逻辑存在问题：

- **现状**: `run_batch.py` 只启动 pytest 执行，不解析结果
- **缺失**: pytest 输出解析 → 生成符合 schema 的 `batch_results.json`
- **影响**: Stage 3 到 Stage 4 的数据流断裂

### 已完成事项

- [x] **设计 pytest 结果解析逻辑** (待实施)
  - 背景: `run_batch.py` 目前只启动 pytest，没有结果解析
  - 位置: `skills/ut/unit-test-executor/scripts/`
  - 需求:
    1. 解析 pytest stdout/stderr
    2. 提取每个测试的 status (passed/failed/error)
    3. 分类 error_type (dependency/network/resource/version/functional/download_error/other)
    4. 提取 duration_ms, exit_code, error_message
    5. 生成符合 `batch_results_schema.json` 的 JSON 文件
  - 优先级: P1
  - 状态: 设计完成，待实施

- [x] **添加 schema 校验到所有 JSON 生成脚本** ✅ 2026-06-11 完成
  - 背景: 所有脚本输出 JSON 前缺少 schema 验证
  - 涉及脚本:
    - `init_workflow_state.py` → workflow_state.json ✅
    - `generate_batch.py` → batch_config.json ✅
    - `generate_handled_manifest.py` → handled_tests.json ✅
    - `update_status.py` → manifest.json ✅
    - `supervisor_loop.py` → workflow.yaml 启动前校验 ✅
  - 需求:
    1. 创建通用校验函数 `validate_schema.py` ✅
    2. 在每个脚本输出 JSON 前调用校验 ✅
    3. 校验失败时输出具体错误信息 ✅
  - 优先级: P1
  - 状态: **已完成**

### 实施记录 (2026-06-11)

**Phase 1**: Schema文件迁移 + `_enum_comments` 注释添加
- batch_config_schema.json → skills/ut/batch-selector/
- batch_results_schema.json → skills/ut/unit-test-executor/
- handled_tests_schema.json → skills/ut/failure-handler/
- workflow_state_schema.json → skills/ut/supervisor/
- workflow_schema.yaml → skills/ut/supervisor/ (新建)
- manifest_schema.json → skills/ut/shared/ (已更新)

**Phase 2**: 校验脚本创建
- validate_schema.py → skills/ut/shared/
- 功能: validate_json(), validate_yaml(), validate_and_write()

**Phase 3**: 迁移脚本创建
- migrate_manifest.py → skills/ut/shared/
- 执行迁移: tasks/ut/test_analysis/manifest.json
- 备份: manifest_legacy.json

**Phase 4**: 脚本集成校验
- supervisor_loop.py: workflow.yaml 启动前校验
- init_workflow_state.py: workflow_state.json 校验
- generate_batch.py: batch_config.json 校验
- generate_handled_manifest.py: handled_tests.json 校验
- update_status.py: manifest.json 校验

---

## 模板

```markdown
- [ ] **任务标题**
  - 背景: 为什么需要这个任务
  - 位置: 涉及的文件路径
  - 需求: 具体要做什么
  - 优先级: P0/P1/P2/P3
  - 依赖: 前置任务或条件
```