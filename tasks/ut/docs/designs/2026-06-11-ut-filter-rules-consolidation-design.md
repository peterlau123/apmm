# UT Workflow 过滤规则汇聚设计

> **状态**: 设计完成，待实施
> **优先级**: 等待 todo.md P1 待办完成后执行
> **创建日期**: 2026-06-11

---

## 背景

UT workflow 的过滤规则分散在 7+ 个位置，导致：
- 规则版本不一致（部分文档只有简化版）
- 工作期间难以找到统一来源
- 更新规则时需要同步多处

---

## 设计目标

建立过滤规则的**单一来源**：
- 所有脚本从同一文件读取
- 所有文档引用同一来源
- 带时间戳标记当前规则版本

---

## 设计要点

### 1. filter_rules.yaml 结构

**位置**: `skills/ut/ut_common/filter_rules.yaml`

**格式**: 纯 YAML，便于脚本直接加载

```yaml
# UT Workflow 过滤规则
# 单一来源：所有脚本从此文件读取
# 最后更新：2026-06-11

filter_rules:
  updated_at: "2026-06-11T00:00:00"
  
  rules:
    # === 硬件平台（排除） ===
    - pattern: "tests/**/*rocm*"
      type: "exclude"
      reason: "ROCm 硬件不支持"
    
    - pattern: "tests/tpu/*"
      type: "exclude"
      reason: "TPU 目录"
    
    # ... 更多规则
    
    # === Distributed（识别，不排除） ===
    - pattern: "tests/distributed/"
      type: "distributed"
      reason: "distributed 目录下的测试"
```

**type 字段说明**:
- `exclude`: 排除规则，不出现在 manifest 中
- `distributed`: 识别规则，需要多 GPU 执行（不排除）

---

### 2. workflow.yaml input_filter 块

**新增配置块**（独立于 config）:

```yaml
input_filter:
  test_list_path: null          # 场景 1: 用户指定的 test_list.txt
  manifest_source: null         # 场景 2: 用户指定的输入 manifest.json
  
  range: null                   # 格式: "0-100" 或 "50:100"
  
  filter:
    status: null                # ["pending", "failed", ...] 或 null(全部)
    error_type: null            # ["dependency", "network", ...] 或 null(全部)
    count: null                 # N: 跑多少个，null 表示筛选后全部
```

---

### 3. pytest_config.py 变化

**移除**: 所有过滤规则（~37 条 ignore-glob）

**保留**: 
- `-q` (quiet 模式)
- `--tb=long` (详细回溯)

**新增**: `skills/ut/ut_common/load_filter_rules.py`

---

### 4. Stage 1 输入处理逻辑

| 场景 | 用户输入 | 参数 | Workflow 动作 |
|------|----------|------|---------------|
| **1. test_list.txt** | `test_list_path` 指定 | `range`（可选） | 读取 → 应用 range → 生成 manifest.json |
| **2.1. manifest + range** | `manifest_source` 指定 | `range` 指定 | 读取 → 截取范围 → 写入新 manifest.json |
| **2.2. manifest + filter** | `manifest_source` 指定 | `status`, `error_type`, `count` | 读取 → 筛选 → 截取 N → 写入新 manifest.json |
| **3. 两者都指定** | 两者都有 | — | 提示用户确认以哪个为准 |
| **4. 两者都没指定** | 都为 null | — | 提示用户是否跑内置过滤后的全量清单 |

---

### 5. 场景 4 远程 pytest collect

**触发条件**: 用户确认要跑全量清单

**执行方式**:
- 远程 t_h20 容器
- `pytest tests/ --collect-only` + 所有 exclude 规则
- 解析输出生成 manifest.json

---

### 6. 文档更新

| 文件 | 更新内容 |
|------|----------|
| ut-test-collector/SKILL.md | 新增 4 种场景输入逻辑 |
| batch-selector/SKILL.md | 移除硬编码，改为引用 |
| AGENTS.md, GOAL.md, testing.md, README.md | 移除规则列表，改为引用链接 |

---

## 实施优先级

等待 `tasks/ut/todo.md` 中的 P1 待办完成后执行：

| 前置任务 | 优先级 | 状态 |
|----------|:------:|:----:|
| tasks/ut/ 文件清理（42 个文件） | P1 | 待执行 |
| PROGRESS.md 与 WORKLOG.md 整理 | P1 | 待执行 |

---

## 完整过滤规则清单

用户提供的完整过滤规则（37 条）已记录在设计文档中。

---

*创建日期: 2026-06-11*
*状态: 设计完成，待实施*