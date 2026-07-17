# UT Workflow dependency_classification 优化设计

> **Date:** 2026-06-28
> **Status:** Approved
> **Related:** `docs/superpowers/specs/2026-06-28-ut-status-classification-design.md` (原始设计)
> **Decision:** 方案 B2 - Executor placeholder schema + Agent 直接输出

---

## 概述

优化 `dependency_classification` 字段的实现，减少硬编码，明确两阶段 classification 的职责分工。

**核心问题：**
- Executor 硬编码 `dependency_classification`（临时占位符）
- Stage 4 原设计通过 `llm_invoker` 调用 LLM（过度抽象）
- Worker Agent 本身就是 LLM，不需要中间层

**优化方案：**
- Executor 返回 placeholder schema（明确语义，提供 executor_signal + executor_evidence）
- Worker Agent 直接输出 classification（去掉 llm_invoker 抽象）
- Python 脚本只做 schema validation + 组装

---

## 1. 架构设计

### 1.1 两阶段 Classification

```
┌─────────────┐                    ┌──────────────┐
│  Executor   │                    │   Stage 4    │
│ (execute_   │                    │ (failure-    │
│  batch.py)  │                    │  handler)    │
└─────────────┘                    └──────────────┘
      │                                  │
      │ timeout 检测                      │ Agent 直接输出
      │                                  │
      ▼                                  ▼
┌─────────────────────────┐    ┌─────────────────────┐
│   batch_results.json    │───►│  handled_tests.json │
│                         │    │                     │
│  dependency_            │    │  dependency_        │
│  classification:        │    │  classification:    │
│  {                      │    │  {                  │
│    "status": "pending", │    │    "classification":│
│    "executor_signal":   │    │      "dep_stall",   │
│      "timeout_no_xml",  │    │    "evidence": ..., │
│    "executor_evidence": │    │    "dependency_hint"│
│      "..."              │    │  }                  │
│  }                      │    │                     │
│  (placeholder schema)   │    │  (final schema)     │
└─────────────────────────┘    └─────────────────────┘
```

**关键点：**
- Executor 返回 **placeholder schema**（字段名不同：executor_signal + executor_evidence）
- Stage 4 替换为 **final schema**（标准字段：classification + evidence + dependency_hint）
- 两阶段 schema 不同，语义清晰

---

### 1.2 Worker Agent 直接输出（去掉 llm_invoker）

**优化前（过度抽象）：**
```
Worker Agent (本身就是 LLM)
    ↓
llm_invoker (再调用另一个 LLM)  ← 多余的中间层
    ↓
调用 LLM API
    ↓
返回 JSON
```

**优化后（简洁）：**
```
Worker Agent (Claude)
    ↓
理解固化 Prompt（在 SKILL.md §X）
    ↓
直接输出 classification JSON
    ↓
调用 Python script 进行 schema validation
```

**Worker Agent 职责：**
- 读取 log tail（从 batch_dir/summary.txt）
- 理解固化 Prompt（一字不改地理解）
- 直接输出 classification JSON（严格遵循输出格式要求）
- 调用 Python 脚本，传入 `agent_classification`

**Python 脚本职责：**
- 接收 Agent 输出的 classification
- Schema validation（匹配 dependency_stall_schema.json）
- 组装 handled_tests entry
- 任何 validation failure → fallback to "unknown"

---

## 2. Executor Placeholder Schema

### 2.1 Schema 定义

```python
# execute_batch.py timeout 返回的 placeholder

# XML missing timeout
{
    "status": "ignored",
    "error_type": "timeout",
    "error_message": "JUnit XML is empty (pytest-timeout or watchdog)",
    "dependency_classification": {
        "status": "pending",  # ← 明确标记：等待 Stage 4 处理
        "executor_signal": "timeout_no_xml",  # ← Executor 检测到的信号
        "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
    }
}

# Bastion disconnect timeout
{
    "status": "ignored",
    "error_type": "timeout",
    "error_message": "bastion disconnect during exec",
    "dependency_classification": {
        "status": "pending",
        "executor_signal": "disconnect_exec",
        "executor_evidence": "bastion disconnect during test exec"
    }
}
```

### 2.2 executor_signal 枚举

```python
EXECUTOR_SIGNALS = {
    "timeout_no_xml": "XML missing after watchdog SIGKILL",
    "timeout_unparseable_xml": "XML unparseable (ET.ParseError)",
    "timeout_no_testcase": "XML has no testcase element",
    "disconnect_exec": "Bastion disconnect during test exec",
    "disconnect_xml_fetch": "Bastion disconnect during xml fetch"
}
```

**executor_signal 的价值：**
- 提供 Executor 能检测到的真实信息
- 运维人员知道 timeout 的具体原因（disconnect vs XML missing）
- Stage 4 可参考 executor_signal 优化分类决策（可选）

---

## 3. Worker Agent 输出格式约束

### 3.1 固化 Prompt（一字不改）

```text
以下是一个 pytest batch 因 idle/wall-clock timeout 被 kill 后的日志末尾内容。

判断这次 timeout 的真因，分类为以下三者之一：

1. "dep_stall" — 因「依赖资源未就绪」而 hang，典型证据：
   - HuggingFace 模型下载中
   - pip install 中
   - HF cache miss / auth token 等待
   - 任何形式的「正在等待网络资源到位」

2. "not_dep_stall" — 看不到上述迹象，更像是：
   - 测试代码本身 hang / 死锁
   - GPU OOM / CUDA error
   - SSH transport drop（log 末尾正常 PASSED 后无新内容）
   - 其它非依赖资源类的卡死

3. "unknown" — 看不清属于哪类；判不准时优先选这个（保守）。

【输出格式要求】
输出严格 JSON（无 markdown fence、无前后文）：
{
  "classification": "<dep_stall | not_dep_stall | unknown>",
  "evidence": "<引用 log 里一行原文作为依据>",
  "dependency_hint": "<具体资源名，如 'meta-llama/Llama-3.2-1B' 或 'mteb' 包名；非 dep_stall 时为 null>"
}

【约束规则】
- evidence 必填且必须来自 log；不允许编造或泛述。
- classification 必须是三个枚举值之一。
- dependency_hint：dep_stall 时填写资源名，否则为 null。
- 输出纯 JSON，不要包裹在 ```json``` fence 中。

LOG 末尾内容如下:
---
{log_tail}
---
```

### 3.2 Schema Validation

Agent 输出必须匹配 `skills/ut/ut_common/dependency_stall_schema.json`：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["classification", "evidence"],
  "properties": {
    "classification": {
      "type": "string",
      "enum": ["dep_stall", "not_dep_stall", "unknown"]
    },
    "evidence": {
      "type": "string",
      "minLength": 1
    },
    "dependency_hint": {
      "oneOf": [
        {"type": "string"},
        {"type": "null"}
      ]
    }
  }
}
```

### 3.3 三重约束机制

1. **Prompt 约束** - 固化 Prompt 明确规定输出格式
2. **Schema validation** - Python 脚本验证 JSON schema
3. **Fallback 机制** - 任何失败 → fallback to "unknown"（永不 crash）

---

## 4. Python 脚本修改

### 4.1 函数签名变化

```python
# 当前设计（过度抽象）
def _handle_timeout_test(
    test: dict,
    batch_dir: Path | None,
    *,
    log_tail_fetcher=None,
    llm_invoker=None,  # ← 删除这个参数
) -> dict | None:

# 优化后设计
def _handle_timeout_test(
    test: dict,
    batch_dir: Path | None,
    *,
    log_tail_fetcher=None,
    agent_classification: dict | None = None,  # ← 新参数
) -> dict | None:
    """
    Args:
        agent_classification: Worker Agent 已输出的 classification dict.
            格式必须匹配 dependency_stall_schema.json.
            如果为 None 或 schema invalid → fallback to "unknown"
    """
```

### 4.2 处理逻辑

```python
def _handle_timeout_test(
    test: dict,
    batch_dir: Path | None,
    *,
    log_tail_fetcher=None,
    agent_classification: dict | None = None,
) -> dict | None:
    test_node = test.get("test_node")
    error_message = (test.get("error_message") or "")[:500]
    
    # 读取 log tail（用于 fallback）
    if log_tail_fetcher is not None:
        log_tail = log_tail_fetcher(test) or ""
    else:
        log_tail = _read_log_tail_from_summary(batch_dir)
    
    # Schema validation（Agent 输出的 JSON）
    if agent_classification is not None:
        result = classify_dep_stall.classify(log_tail, json.dumps(agent_classification))
    else:
        # Agent 未提供 → fallback to unknown
        result = classify_dep_stall._fallback_unknown(log_tail, reason="no_agent_input")
    
    reason = classify_dep_stall.ignored_reason_for(result)
    
    if reason is None:
        # not_dep_stall → Stage 2 retry
        return None
    
    return {
        "test_node": test_node,
        "final_status": "ignored",
        "error_type": "timeout",
        "error_message": error_message,
        "ignored_reason": reason,
        "resolution": {
            "status": "ignored",
            "action": "skip",
            "dependency_classification": classify_dep_stall.strip_internal_fields(result),
        },
    }
```

---

## 5. Edge Cases 处理

### 5.1 Fallback 决策表

| Edge Case | Fallback 结果 | 最终 ignored_reason |
|---|---|---|
| Agent 输出 schema invalid | `"unknown"` | `"分类不明 (LLM 未识别 / schema mismatch)"` |
| Agent 未提供 classification | `"unknown"` | `"分类不明 (no_agent_input)"` |
| JSON decode error | `"unknown"` | `"分类不明 (json_decode_error)"` |
| Evidence 为空 | `"unknown"` | `"分类不明 (empty evidence)"` |
| Agent crash/timeout | `"unknown"` | `"分类不明 (agent failure)"` |

**所有 Edge Case 都 fallback to `"unknown"` → 永不 crash。**

### 5.2 Executor Signal 传递

```python
# Executor placeholder 包含有价值的信息
executor_placeholder = {
    "status": "pending",
    "executor_signal": "disconnect_exec",  # ← 知道是 disconnect 导致的
    "executor_evidence": "bastion disconnect during test exec"
}

# Stage 4 可以参考 executor_signal（可选）
# Disconnect 通常不是 dep_stall，Agent 可倾向于 "not_dep_stall" 或 "unknown"
```

---

## 6. 测试策略

### 6.1 单元测试

```python
# tests/ut/unit/test_handle_timeout_classification.py

def test_agent_classification_dep_stall_accepted():
    """Agent 输出 dep_stall → Python 正常处理"""
    ...

def test_agent_classification_schema_invalid_fallback():
    """Agent 输出 schema invalid → fallback to unknown"""
    ...

def test_agent_classification_none_fallback():
    """Agent 未提供 classification → fallback to unknown"""
    ...

def test_executor_placeholder_preserved():
    """Executor placeholder 在 batch_results.json 中保留"""
    ...

def test_executor_signal_types():
    """Executor 能检测的信号类型"""
    ...
```

### 6.2 E2E 测试

```python
# tests/ut/integration/test_timeout_classification_e2e.py

def test_full_timeout_flow_with_dep_stall():
    """完整 flow：Executor → Stage 4 → handled_tests.json"""
    ...

def test_full_timeout_flow_with_disconnect():
    """disconnect timeout：executor_signal 传递到 Stage 4"""
    ...
```

---

## 7. 文档更新清单

| 文档路径 | 更新内容 |
|---|---|
| `docs/superpowers/specs/2026-06-28-ut-status-classification-design.md` | Append §X：Executor placeholder schema + Agent 直接输出 |
| `skills/ut/unit-test-executor/SKILL.md` | 添加 timeout → placeholder schema 说明 |
| `skills/ut/ut_common/batch_results_schema.json` | 添加 `dependency_classification` 字段定义（placeholder schema） |
| `skills/ut/failure-handler/scripts/generate_handled_manifest.py` | 修改 `_handle_timeout_test()` 参数 |
| `skills/ut/unit-test-executor/scripts/execute_batch.py` | 修改 timeout 返回，添加 placeholder schema |

---

## 8. 向后兼容性

**batch_results_schema.json 变化：**
- ✅ 新字段 `dependency_classification` 是 **optional**
- ✅ 旧 executor 不返回此字段，batch_results.json 仍有效
- ✅ Stage 4 代码兼容新旧格式：无 dependency_classification → fallback

**迁移策略：**
- Phase 1: Executor 输出 placeholder（向后兼容）
- Phase 2: Stage 4 处理 Agent classification（向后兼容）
- Phase 3: 部署验证（单元测试 + E2E test）

---

## 9. 实现优先级

**P0（必须实现）：**
- Executor placeholder schema（execute_batch.py）
- batch_results_schema.json 添加字段定义
- Python 脚本参数修改（generate_handled_manifest.py）

**P1（应该实现）：**
- 单元测试覆盖
- 文档更新

**P2（可选）：**
- E2E test（完整 flow 验证）
- executor_signal 传递优化（Stage 4 参考 executor_signal）

---

*Design created: 2026-06-28*