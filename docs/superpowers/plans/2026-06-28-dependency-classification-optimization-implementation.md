# dependency_classification 优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 dependency_classification 字段实现，Executor 返回 placeholder schema，Worker Agent 直接输出 classification，Python 脚本只做 validation

**Architecture:** 两阶段 schema（Executor placeholder: executor_signal + executor_evidence；Stage 4 final: classification + evidence + dependency_hint）。去掉 llm_invoker 抽象，Agent 直接输出 JSON，Python 脚本验证 schema 并 fallback to unknown。

**Tech Stack:** Python 3.10+, jsonschema, pytest, JSON Schema draft-07

---

## File Structure

| File | Responsibility |
|---|---|
| `skills/ut/unit-test-executor/batch_results_schema.json` | Executor 输出 schema（添加 dependency_classification 字段定义） |
| `skills/ut/unit-test-executor/scripts/execute_batch.py` | Executor timeout 返回 placeholder schema（5 处修改） |
| `skills/ut/ut_common/dependency_stall_schema.json` | Agent 输出验证 schema（已存在，无需修改） |
| `skills/ut/failure-handler/scripts/classify_dependency_stall.py` | Validation + fallback logic（已存在，无需修改） |
| `skills/ut/failure-handler/scripts/generate_handled_manifest.py` | 参数修改（llm_invoker → agent_classification） |
| `tests/ut/unit/test_dependency_classification.py` | 单元测试（placeholder schema + agent classification + full flow） |
| `skills/ut/unit-test-executor/SKILL.md` | 文档：Executor placeholder schema 说明 |
| `docs/superpowers/specs/2026-06-28-ut-status-classification-design.md` | 文档：Append §X：Agent 直接输出 |

---

## Task 1: Update batch_results_schema.json - Add dependency_classification field definition

**Files:**
- Modify: `skills/ut/unit-test-executor/batch_results_schema.json`

**Context:**
Executor timeout 返回需要包含 placeholder schema（executor_signal + executor_evidence），该字段是 optional，向后兼容旧 executor。

- [ ] **Step 1: Add dependency_classification field to schema**

在 `skills/ut/unit-test-executor/batch_results_schema.json` 的 `tests[].properties` 中添加 `dependency_classification` 字段定义：

```json
"dependency_classification": {
  "type": ["object", "null"],
  "description": "Executor placeholder schema for timeout tests. Contains executor_signal + executor_evidence. Stage 4 will replace with final schema.",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["pending"],
      "description": "Placeholder marker — waiting for Stage 4 processing"
    },
    "executor_signal": {
      "type": "string",
      "enum": ["timeout_no_xml", "timeout_unparseable_xml", "timeout_no_testcase", "disconnect_exec", "disconnect_xml_fetch"],
      "description": "Executor-detected timeout signal type"
    },
    "executor_evidence": {
      "type": "string",
      "description": "Executor-detected evidence for timeout"
    }
  },
  "required": ["status", "executor_signal", "executor_evidence"],
  "additionalProperties": false
}
```

**完整的修改位置：**
在 `batch_results_schema.json` 第 121 行（`xml_path` 定义之后）插入该字段。

- [ ] **Step 2: Verify schema syntax**

Run: `python -c "import json; json.load(open('skills/ut/unit-test-executor/batch_results_schema.json'))"`
Expected: No error (valid JSON)

- [ ] **Step 3: Commit**

```bash
git add skills/ut/unit-test-executor/batch_results_schema.json
git commit -m "feat(ut): add dependency_classification placeholder field to batch_results_schema"
```

---

## Task 2: Update execute_batch.py - Replace timeout hardcoded classification with placeholder schema (5 locations)

**Files:**
- Modify: `skills/ut/unit-test-executor/scripts/execute_batch.py`

**Context:**
Executor 有 5 处 timeout 返回硬编码的 `dependency_classification: {"classification": "...", "signal": "unknown"}`，需要替换为 placeholder schema（executor_signal + executor_evidence）。

**5 个 timeout locations:**
1. Line 388: XML missing timeout
2. Line 401: XML unparseable timeout
3. Line 413: No testcase timeout
4. Line 869: Bastion disconnect during exec
5. Line 898: Bastion disconnect during xml fetch

- [ ] **Step 1: Write the failing test**

Create test to verify placeholder schema structure:

```python
# tests/ut/unit/test_execute_batch_placeholder.py

def test_timeout_xml_missing_placeholder_schema():
    """Verify XML missing timeout returns placeholder schema with executor_signal + executor_evidence"""
    import json
    from skills.ut.unit_test_executor.batch_results_schema import _load_schema
    from jsonschema import validate

    # Simulate executor output for XML missing timeout
    mock_output = {
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "JUnit XML missing (watchdog SIGKILL or fetch empty)",
        "duration_ms": None,
        "exit_code": 124,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "timeout_no_xml",
            "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
        }
    }

    # Validate against schema
    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)
    # Should pass - new placeholder schema is valid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ut/unit/test_execute_batch_placeholder.py::test_timeout_xml_missing_placeholder_schema -v`
Expected: FAIL - current schema does not accept executor_signal field

- [ ] **Step 3: Update timeout location 1 (XML missing)**

在 `execute_batch.py` 第 388 行修改：

```python
# Before:
"dependency_classification": {"classification": "timeout_no_xml", "signal": "unknown"}

# After:
"dependency_classification": {
    "status": "pending",
    "executor_signal": "timeout_no_xml",
    "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
}
```

- [ ] **Step 4: Update timeout location 2 (XML unparseable)**

在 `execute_batch.py` 第 401 行修改：

```python
# Before:
"dependency_classification": {"classification": "timeout_unparseable_xml", "signal": "unknown"}

# After:
"dependency_classification": {
    "status": "pending",
    "executor_signal": "timeout_unparseable_xml",
    "executor_evidence": "JUnit XML unparseable (ET.ParseError)"
}
```

- [ ] **Step 5: Update timeout location 3 (No testcase)**

在 `execute_batch.py` 第 413 行修改：

```python
# Before:
"dependency_classification": {"classification": "timeout_no_testcase", "signal": "unknown"}

# After:
"dependency_classification": {
    "status": "pending",
    "executor_signal": "timeout_no_testcase",
    "executor_evidence": "JUnit XML has no testcase element"
}
```

- [ ] **Step 6: Update timeout location 4 (Disconnect exec)**

在 `execute_batch.py` 第 869 行修改：

```python
# Before:
"dependency_classification": {"classification": "disconnect_exec", "signal": "unknown"}

# After:
"dependency_classification": {
    "status": "pending",
    "executor_signal": "disconnect_exec",
    "executor_evidence": "bastion disconnect during test exec"
}
```

- [ ] **Step 7: Update timeout location 5 (Disconnect xml fetch)**

在 `execute_batch.py` 第 898 行修改：

```python
# Before:
"dependency_classification": {"classification": "disconnect_xml_fetch", "signal": "unknown"}

# After:
"dependency_classification": {
    "status": "pending",
    "executor_signal": "disconnect_xml_fetch",
    "executor_evidence": "bastion disconnect during xml fetch"
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/ut/unit/test_execute_batch_placeholder.py::test_timeout_xml_missing_placeholder_schema -v`
Expected: PASS - placeholder schema validated

- [ ] **Step 9: Commit**

```bash
git add skills/ut/unit-test-executor/scripts/execute_batch.py tests/ut/unit/test_execute_batch_placeholder.py
git commit -m "feat(ut): executor timeout returns placeholder schema with executor_signal + executor_evidence"
```

---

## Task 3: Update generate_handled_manifest.py - Replace llm_invoker parameter with agent_classification

**Files:**
- Modify: `skills/ut/failure-handler/scripts/generate_handled_manifest.py`

**Context:**
去掉 llm_invoker 抽象，Worker Agent 直接输出 classification JSON，Python 脚本接收 `agent_classification` 参数并验证 schema。

- [ ] **Step 1: Write the failing test**

```python
# tests/ut/unit/test_generate_handled_manifest_agent_classification.py

def test_agent_classification_parameter_accepted():
    """Verify generate_handled_manifest accepts agent_classification parameter"""
    from pathlib import Path
    from skills.ut.failure_handler.scripts.generate_handled_manifest import _handle_timeout_test

    mock_test = {
        "test_node": "test_example",
        "error_message": "timeout"
    }
    mock_batch_dir = Path("/tmp/batch_123")

    mock_agent_classification = {
        "classification": "dep_stall",
        "evidence": "Downloading meta-llama/Llama-3.2-1B",
        "dependency_hint": "meta-llama/Llama-3.2-1B"
    }

    result = _handle_timeout_test(
        mock_test,
        mock_batch_dir,
        agent_classification=mock_agent_classification
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert "dependency_classification" in result["resolution"]
    assert result["resolution"]["dependency_classification"]["classification"] == "dep_stall"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ut/unit/test_generate_handled_manifest_agent_classification.py::test_agent_classification_parameter_accepted -v`
Expected: FAIL - current code uses llm_invoker parameter

- [ ] **Step 3: Update _handle_timeout_test parameter signature**

在 `generate_handled_manifest.py` 第 100-106 行修改函数签名：

```python
# Before:
def _handle_timeout_test(
    test: dict,
    batch_dir: Path | None,
    *,
    log_tail_fetcher=None,
    llm_invoker=None,
) -> dict | None:

# After:
def _handle_timeout_test(
    test: dict,
    batch_dir: Path | None,
    *,
    log_tail_fetcher=None,
    agent_classification: dict | None = None,
) -> dict | None:
    """
    Args:
        agent_classification: Worker Agent 已输出的 classification dict.
            格式必须匹配 dependency_stall_schema.json.
            如果为 None 或 schema invalid → fallback to "unknown"
    """
```

- [ ] **Step 4: Update _handle_timeout_test processing logic**

在 `generate_handled_manifest.py` 第 126-134 行修改逻辑：

```python
# Before:
prompt = classify_dep_stall.render_prompt(log_tail)
llm_output = None
if llm_invoker is not None:
    try:
        llm_output = llm_invoker(prompt)
    except Exception:  # noqa: BLE001 — never let the LLM call kill the stage
        llm_output = None

result = classify_dep_stall.classify(log_tail, llm_output)

# After:
# Agent 已输出 classification，直接验证 schema
if agent_classification is not None:
    result = classify_dep_stall.classify(log_tail, json.dumps(agent_classification))
else:
    # Agent 未提供 → fallback to unknown
    result = classify_dep_stall._fallback_unknown(log_tail, reason="no_agent_input")
```

- [ ] **Step 5: Update generate_handled_manifest parameter signature**

在 `generate_handled_manifest.py` 第 157-164 行修改：

```python
# Before:
def generate_handled_manifest(
    batch_id: str,
    batch_results_path: Path,
    batch_dir: Path = None,
    *,
    log_tail_fetcher=None,
    llm_invoker=None,
) -> dict:

# After:
def generate_handled_manifest(
    batch_id: str,
    batch_results_path: Path,
    batch_dir: Path = None,
    *,
    log_tail_fetcher=None,
    agent_classification: dict | None = None,
) -> dict:
```

- [ ] **Step 6: Update generate_handled_manifest call**

在 `generate_handled_manifest.py` 第 192-196 行修改：

```python
# Before:
entry = _handle_timeout_test(
    test, batch_dir,
    log_tail_fetcher=log_tail_fetcher,
    llm_invoker=llm_invoker,
)

# After:
entry = _handle_timeout_test(
    test, batch_dir,
    log_tail_fetcher=log_tail_fetcher,
    agent_classification=agent_classification,
)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/ut/unit/test_generate_handled_manifest_agent_classification.py::test_agent_classification_parameter_accepted -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add skills/ut/failure-handler/scripts/generate_handled_manifest.py tests/ut/unit/test_generate_handled_manifest_agent_classification.py
git commit -m "feat(ut): replace llm_invoker with agent_classification parameter in generate_handled_manifest"
```

---

## Task 4: Add comprehensive unit tests for dependency classification

**Files:**
- Create: `tests/ut/unit/test_dependency_classification.py`

**Context:**
完整测试 placeholder schema + agent classification + fallback logic + executor signal preservation。

- [ ] **Step 1: Write test - Agent classification dep_stall accepted**

```python
# tests/ut/unit/test_dependency_classification.py

import json
from pathlib import Path
from skills.ut.failure_handler.scripts.generate_handled_manifest import _handle_timeout_test


def test_agent_classification_dep_stall_accepted():
    """Agent outputs dep_stall → Python script processes correctly"""
    mock_test = {
        "test_node": "tests/test_example.py::test_hf_download",
        "error_message": "JUnit XML missing"
    }

    mock_agent_classification = {
        "classification": "dep_stall",
        "evidence": "Downloading meta-llama/Llama-3.2-1B",
        "dependency_hint": "meta-llama/Llama-3.2-1B"
    }

    result = _handle_timeout_test(
        mock_test,
        None,
        agent_classification=mock_agent_classification
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert result["resolution"]["dependency_classification"]["classification"] == "dep_stall"
    assert result["resolution"]["dependency_classification"]["dependency_hint"] == "meta-llama/Llama-3.2-1B"
```

- [ ] **Step 2: Write test - Agent classification schema invalid fallback**

```python
def test_agent_classification_schema_invalid_fallback():
    """Agent outputs schema invalid JSON → fallback to unknown"""
    mock_test = {
        "test_node": "tests/test_example.py::test_example",
        "error_message": "timeout"
    }

    # Schema invalid: missing required "evidence" field
    mock_agent_classification = {
        "classification": "dep_stall",
        "dependency_hint": "some-model"
    }

    result = _handle_timeout_test(
        mock_test,
        None,
        agent_classification=mock_agent_classification
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert result["resolution"]["dependency_classification"]["classification"] == "unknown"
```

- [ ] **Step 3: Write test - Agent classification None fallback**

```python
def test_agent_classification_none_fallback():
    """Agent does not provide classification → fallback to unknown"""
    mock_test = {
        "test_node": "tests/test_example.py::test_example",
        "error_message": "timeout"
    }

    result = _handle_timeout_test(
        mock_test,
        None,
        agent_classification=None  # Agent未提供
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert result["resolution"]["dependency_classification"]["classification"] == "unknown"
```

- [ ] **Step 4: Write test - Executor placeholder preserved**

```python
def test_executor_placeholder_preserved_in_batch_results():
    """Executor placeholder schema is preserved in batch_results.json"""
    from skills.ut.unit_test_executor.batch_results_schema import _load_schema
    from jsonschema import validate

    mock_batch_result = {
        "batch_id": "batch_test_123",
        "started_at": "2026-06-28T10:00:00Z",
        "finished_at": "2026-06-28T10:05:00Z",
        "exit_code": 124,
        "remote_log": {
            "host": "t_h20",
            "container": "v0.13.0_torch2.5.1_compile",
            "raw_log_path": "/gpfs/pytest_batch_test_123.log",
            "size_bytes": 1024,
            "captured_at": "2026-06-28T10:05:00Z"
        },
        "tests": [
            {
                "id": 1,
                "test_node": "tests/test_example.py::test_example",
                "status": "ignored",
                "error_type": "timeout",
                "error_message": "JUnit XML missing",
                "duration_ms": None,
                "exit_code": 124,
                "gpu_id": 0,
                "log_path": "/gpfs/pytest_batch_test_123_1.log",
                "xml_path": None,
                "dependency_classification": {
                    "status": "pending",
                    "executor_signal": "timeout_no_xml",
                    "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
                }
            }
        ],
        "statistics": {
            "total": 1,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "retriable_error": 0,
            "ignored": 1
        }
    }

    schema = _load_schema()
    validate(mock_batch_result, schema)
    # Should pass - placeholder schema is valid
```

- [ ] **Step 5: Write test - Executor signal types enumeration**

```python
def test_executor_signal_types():
    """Executor can detect 5 signal types"""
    executor_signals = [
        "timeout_no_xml",
        "timeout_unparseable_xml",
        "timeout_no_testcase",
        "disconnect_exec",
        "disconnect_xml_fetch"
    ]

    from skills.ut.unit_test_executor.batch_results_schema import _load_schema
    schema = _load_schema()
    signal_enum = schema["properties"]["tests"]["items"]["properties"]["dependency_classification"]["properties"]["executor_signal"]["enum"]

    assert set(executor_signals) == set(signal_enum)
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ut/unit/test_dependency_classification.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add tests/ut/unit/test_dependency_classification.py
git commit -m "test(ut): add comprehensive unit tests for dependency classification optimization"
```

---

## Task 5: Run full unit test suite and verify all tests pass

**Files:**
- None (validation only)

**Context:**
验证所有单元测试通过，确保向后兼容（旧 executor 不返回 dependency_classification 字段时 batch_results.json 仍有效）。

- [ ] **Step 1: Run all UT unit tests**

Run: `python -m pytest tests/ut/unit/ -q`
Expected: All tests pass (372+ tests)

- [ ] **Step 2: Verify backward compatibility test**

检查是否有 backward compatibility 测试（旧 executor 不返回 dependency_classification）：

```python
# 如果没有，添加一个简单的 backward compatibility test
def test_backward_compatibility_old_executor():
    """Old executor without dependency_classification field still valid"""
    from skills.ut.unit_test_executor.batch_results_schema import _load_schema
    from jsonschema import validate

    mock_old_executor_result = {
        "batch_id": "batch_old",
        "started_at": "2026-06-28T10:00:00Z",
        "finished_at": "2026-06-28T10:05:00Z",
        "exit_code": 0,
        "remote_log": {
            "host": "t_h20",
            "container": "v0.13.0",
            "raw_log_path": "/gpfs/pytest.log",
            "size_bytes": 1024,
            "captured_at": "2026-06-28T10:05:00Z"
        },
        "tests": [
            {
                "id": 1,
                "test_node": "tests/test_example.py::test_example",
                "status": "passed",
                "error_type": None,
                "error_message": None,
                "duration_ms": 1000,
                "exit_code": 0
                # No dependency_classification field
            }
        ],
        "statistics": {
            "total": 1,
            "passed": 1,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "retriable_error": 0,
            "ignored": 0
        }
    }

    schema = _load_schema()
    validate(mock_old_executor_result, schema)
    # Should pass - dependency_classification is optional
```

- [ ] **Step 3: Final commit if backward compatibility test added**

```bash
git add tests/ut/unit/test_backward_compatibility.py
git commit -m "test(ut): verify backward compatibility - old executor without dependency_classification still valid"
```

---

## Task 6: Update documentation - Executor placeholder schema and Agent direct output

**Files:**
- Modify: `skills/ut/unit-test-executor/SKILL.md`
- Modify: `docs/superpowers/specs/2026-06-28-ut-status-classification-design.md`

**Context:**
文档更新，说明 Executor placeholder schema 和 Agent 直接输出 classification 的流程。

- [ ] **Step 1: Update unit-test-executor SKILL.md**

在 `skills/ut/unit-test-executor/SKILL.md` 添加 §X 说明 Executor placeholder schema：

```markdown
## §X. Executor Timeout Placeholder Schema

当 Executor 检测到 timeout 时，返回 placeholder schema（而非最终 classification）：

**Placeholder schema structure:**
```json
{
  "status": "pending",
  "executor_signal": "timeout_no_xml | timeout_unparseable_xml | timeout_no_testcase | disconnect_exec | disconnect_xml_fetch",
  "executor_evidence": "Executor-detected evidence for timeout"
}
```

**executor_signal 的价值：**
- 提供 Executor 能检测到的真实信息（XML missing vs disconnect）
- 运维人员知道 timeout 的具体原因
- Stage 4 可参考 executor_signal 优化分类决策（可选）

**注意：**
- Executor 只输出 placeholder，不做最终分类
- Stage 4 Worker Agent 通过固化 Prompt 判断 log tail，输出最终 classification
- Python 脚本验证 Agent 输出的 JSON schema，fallback to "unknown" if invalid
```

- [ ] **Step 2: Update ut-status-classification-design.md**

在 `docs/superpowers/specs/2026-06-28-ut-status-classification-design.md` Append 新 section：

```markdown
---

## §X. 优化：Executor Placeholder Schema + Agent Direct Output

**优化目标：**
减少硬编码，明确两阶段 classification 的职责分工。

**两阶段 schema：**
- **Executor placeholder**: `executor_signal + executor_evidence`（Executor 检测到的信号）
- **Stage 4 final**: `classification + evidence + dependency_hint`（Agent 判断的真因）

**去掉 llm_invoker 抽象：**
- Worker Agent 本身就是 LLM，不需要中间层调用另一个 LLM
- Agent 直接输出 classification JSON（遵循固化 Prompt）
- Python 脚本只做 schema validation + fallback

**向后兼容：**
- dependency_classification 字段是 optional
- 旧 executor 不返回该字段时，batch_results.json 仍有效
- Stage 4 代码兼容新旧格式

**实现细节见：**
`docs/superpowers/specs/2026-06-28-dependency-classification-optimization-design.md`
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/unit-test-executor/SKILL.md docs/superpowers/specs/2026-06-28-ut-status-classification-design.md
git commit -m "docs(ut): document executor placeholder schema and agent direct output optimization"
```

---

## Task 7: Final verification - Run L1 smoke test

**Files:**
- None (validation only)

**Context:**
运行 L1 smoke test 验证完整 flow（timeout detection → placeholder → handled_tests.json）。

- [ ] **Step 1: Run L1 smoke test**

Run: `python -m pytest tests/ut/integration/test_l1_smoke.py -v`
Expected: L1 smoke test pass

- [ ] **Step 2: Verify batch_results.json contains placeholder schema**

检查生成的 batch_results.json 是否包含正确的 placeholder schema：

```bash
cat tests/ut/integration/fixtures/batch_results_timeout_example.json | grep -A 5 "dependency_classification"
```

Expected output:
```json
"dependency_classification": {
  "status": "pending",
  "executor_signal": "...",
  "executor_evidence": "..."
}
```

- [ ] **Step 3: Final commit message summary**

All commits should be ready. Prepare summary commit:

```bash
git log --oneline -10
```

Expected: 6+ commits covering schema, executor, handler, tests, docs.

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ Executor placeholder schema (execute_batch.py 5 locations) — Task 2
- ✅ batch_results_schema.json field definition — Task 1
- ✅ Python script parameter change (generate_handled_manifest.py) — Task 3
- ✅ Unit test coverage — Task 4
- ✅ Documentation update — Task 6
- ✅ Backward compatibility — Task 5
- ✅ executor_signal enumeration — Task 4, Step 5
- ✅ Fallback logic — Task 3, Task 4
- ❌ E2E test (P2 optional — not in this plan)
- ❌ executor_signal transmission optimization (P2 optional — not in this plan)

**2. Placeholder scan:**
- No "TBD", "TODO", "implement later" — ✅
- No "Add appropriate error handling" — ✅
- No "Write tests for the above" (actual test code provided) — ✅
- No "Similar to Task N" — ✅
- All steps show actual code — ✅

**3. Type consistency:**
- executor_signal enum matches schema definition — ✅ (Task 1, Task 2)
- agent_classification parameter type matches classify_dep_stall.classify input — ✅ (Task 3)
- dependency_classification field name consistent across executor and handler — ✅

---

*Plan created: 2026-06-28*