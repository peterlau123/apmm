# UT Workflow Resume机制改进设计文档

**设计日期**: 2026-07-03
**设计者**: Claude Agent
**状态**: Draft (待用户审核)

---

## 1. 背景和问题

### 1.1 问题描述

**当前问题**：
- workflow_state.json 缺少 batches 字段，无法跟踪每个batch的状态
- generate_batch.py 和 execute_batch.py 未更新 workflow_state.json
- update_manifest.py 硬编码路径，不适用于 run_dir 结构
- Agent长时间运行后，可能编写批量脚本自动化整个workflow，脱离控制

**影响**：
- batch统计不准确，resume机制失效
- 无法准确判断执行进度
- 生产环境（terminal-workflow）缺少Agent行为约束

### 1.2 设计目标

1. **Resume机制改进（方案A）**：workflow_state.json 作为单一事实源
2. **统计工具修复**：修复 update_manifest.py，适配 run_dir 结构
3. **Agent行为控制**：防止Agent批量自动化执行，确保逐stage控制

---

## 2. 设计决策

### 2.1 Resume机制优先级

- **决策**: 无约束，优先最佳方案
- **理由**: 用户明确要求先修复resume机制，时间不重要

### 2.2 Event Log必要性

- **决策**: 先做方案A，暂不做方案C（Event Log）
- **理由**: workflow_state.json 已足够，Event Log冗余

### 2.3 manifest-updater处理方式

- **决策**: 修复现有脚本，适配 run_dir 结构
- **理由**: 继续维护 manifest.json，不弃用

### 2.4 workflow_state.json更新时机

- **决策**: 两阶段更新（generated → running → completed）
- **保障**: 三重保障（代码强制 + Supervisor补救 + SKILL.md）
- **理由**: 防止Agent忘记更新

### 2.5 resume.py职责

- **决策**: 只分析状态，输出建议
- **理由**: Agent有判断能力，不需要自动执行

### 2.6 32个中间batch处理

- **决策**: resume机制修复后，用 resume.py 分析处理
- **理由**: resume.py 可以识别中间状态batch

### 2.7 batches字段结构

- **决策**: 添加 gpu_pool 和 batch_size
- **理由**: 便于分析GPU使用和batch大小分布

### 2.8 统计字段命名

- **决策**: test_stats + batch_stats
- **理由**: 命名清晰，避免混淆

---

## 3. 整体架构设计

### 3.1 核心组件

```
skills/ut/
├── shared/
│   └── workflow_state_manager.py  # 新增：状态管理工具函数
│
├── batch-selector/
│   ├── scripts/
│   │   ├── generate_batch.py      # 修改：添加状态更新 + 强制输出
│   └── SKILL.md                   # 修改：添加硬性约束
│
├── unit-test-executor/
│   ├── scripts/
│   │   ├── execute_batch.py       # 修改：添加状态更新 + 强制输出
│   └── SKILL.md                   # 修改：添加硬性约束
│
├── manifest-updater/
│   ├── scripts/
│   │   ├── update_manifest.py     # 修复：适配run_dir结构
│
├── terminal-workflow/
│   ├── scripts/
│   │   ├── loop_executor.py       # 修改：添加自检补救逻辑
│   │   └── resume.py              # 新增：分析状态，输出建议
│   └── SKILL.md                   # 修改：添加硬性约束
│
└── hermes-workflow/
    └── SKILL.md                   # 修改：添加硬性约束
```

### 3.2 文件改动总结

- **新增文件**: 2个（workflow_state_manager.py, resume.py）
- **修改文件**: 7个（generate_batch.py, execute_batch.py, update_manifest.py, 4个SKILL.md）

---

## 4. workflow_state.json 结构设计

### 4.1 完整结构

```json
{
  "workflow": {...},
  "batches": {
    "batch_20260703_093155": {
      "status": "completed",
      "batch_size": 50,
      "gpu_pool": [0, 1, 2, 3],
      "created_at": "2026-07-03T09:31:55Z",
      "started_at": "2026-07-03T09:32:00Z",
      "completed_at": "2026-07-03T09:40:00Z",
      "config_path": "...",
      "results_path": "...",
      "stats": {...}
    }
  },
  "test_stats": {...},
  "batch_stats": {...},
  "resume_info": {...}
}
```

### 4.2 关键字段说明

| 字段 | 说明 |
|------|------|
| `batches` | 记录每个batch的完整生命周期 |
| `batch_stats` | batch级统计：generated/running/completed/failed |
| `test_stats` | test级统计：passed/failed/error/ignored/pending |
| `resume_info` | resume建议，自动计算 |

### 4.3 resume_info 自动计算机制

**写入时机**: 每次更新 workflow_state.json 时自动计算

---

## 5. 核心函数设计

### 5.1 workflow_state_manager.py

```python
def update_batch_generated(...)
def update_batch_running(...)
def update_batch_completed(...)
def calculate_batch_stats(...)
def calculate_test_stats(...)
def calculate_resume_info(...)
```

### 5.2 强制输出逻辑

generate_batch.py 和 execute_batch.py 都添加：
- 状态更新调用
- STAGE COMPLETED 输出
- workflow_state.json 检查

### 5.3 resume.py

```python
def analyze_resume_state(workflow_state_path: Path) -> dict
def analyze_intermediate_batches(workflow_state_path: Path) -> list
```

---

## 6. update_manifest.py 修复方案

参数化路径，移除硬编码 TEST_ANALYSIS_DIR

---

## 7. SKILL.md 硬性约束

4个SKILL.md 都添加：
- 必须更新 workflow_state.json
- 禁止批量自动化执行
- 状态检查要求

---

## 8. terminal-workflow 自检补救逻辑

```python
def check_batch_state(...)
def remediate_batch_state(...)
def run_one_iteration(...)
```

---

## 9. 错误处理

- Agent忘记更新：三重保障
- 文件损坏：异常处理
- batch执行失败：update_batch_failed
- 中间状态batch：resume.py 分析
- 并发冲突：禁止并发

---

## 10. 实施计划

1. 新增 workflow_state_manager.py
2. 修改 generate_batch.py
3. 修改 execute_batch.py
4. 修复 update_manifest.py
5. 新增 resume.py
6. 修改 4个 SKILL.md
7. 修改 loop_executor.py

---

## 附录

### A. 文件路径清单

| 文件 | 改动类型 |
|------|----------|
| workflow_state_manager.py | 新增 |
| generate_batch.py | 修改 |
| execute_batch.py | 修改 |
| update_manifest.py | 修复 |
| resume.py | 新增 |
| loop_executor.py | 修改 |
| 4个 SKILL.md | 修改 |

---

*设计文档结束*