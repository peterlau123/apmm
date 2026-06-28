# UT Workflow 状态分类逻辑修改设计

> **Date:** 2026-06-28
> **Status:** Approved
> **Related:** Code Review Report `tasks/ut/docs/reports/2026-06-28-ut-workflow-code-review.md`

---

## 概述

修改 UT workflow 的状态分类逻辑：
1. `timeout` → `ignored`（保留 dependency_stall 分类器记录）
2. `retriable_error` 只保留 `oom` 一种
3. `error` 类型只有 `version` 进 Stage 4，其他 → `ignored`
4. 修复 `container_env` 未注入 docker exec 的关键缺失

同时修复架构师代码审查发现的 P0/P1 问题。

---

## 1. 状态分类最终规则

### 状态流转矩阵

| 状态/错误类型 | 最终状态 | 处理路径 |
|---|---|---|
| `passed` | ✅ passed | 完成 |
| `failed` (AssertionError) | Stage 4 修复 → fixed_pending_verify 或 failed | 尝试代码修复 |
| `oom` | `retriable_error` → 重试 → passed 或 error | **唯一可重试** |
| `timeout` | **ignored** (保留dependency_stall分类器记录) | 人工处理 |
| `resource` | **ignored** | 人工处理 |
| `dependency` | **ignored** | 人工处理 |
| `download_error` | **ignored** | 人工处理 |
| `network` | **ignored** | 人工处理 |
| `version` | Stage 4 Agent patch → fixed_pending_verify | **唯一error进Stage4** |
| `collection` | **ignored** | 人工处理 |
| `other` | **ignored** | 人工处理 |

### 简化总结

```
retriable_error: 只保留 oom
Stage 4 处理: 只处理 failed + version error
ignored: timeout + resource + dependency + download_error + network + collection + other
```

---

## 2. 代码修改详情

### 2.1 execute_batch.py

**修改点1: `_parse_junit()` - timeout 处理**

```python
# 当前：XML missing → retriable_error
# 修改：XML missing → ignored + 保留分类器记录

def _parse_junit(xml_text, *, exit_code: int, node: str) -> dict:
    if xml_text is None or not xml_text.strip():
        # 调用 dependency_stall 分类器（仅记录，不改变状态）
        classification = classify_dependency_stall(log_tail) if log_tail else {"classification": "unknown"}
        return {
            "status": "ignored",  # 直接 ignored
            "error_type": "timeout",
            "error_message": "JUnit XML missing (watchdog SIGKILL)",
            "dependency_classification": classification  # 保留审计记录
        }
```

**修改点2: `_wrap_with_docker_exec_b64()` - 环境变量注入**

```python
def _wrap_with_docker_exec_b64(docker_container: str, inner_script: str, env_vars: dict | None = None) -> str:
    """Wrap script for docker exec with environment variables injection."""
    env_flags = ""
    if env_vars:
        env_flags = " ".join(f"-e {k}='{v}'" for k, v in env_vars.items())
    encoded = base64.b64encode(inner_script.encode("utf-8")).decode("ascii")
    return (
        f"sudo -n docker exec {env_flags} {docker_container} bash -c "
        f"\"echo {encoded} | base64 -d | bash\""
    )
```

**修改点3: 调用点更新**

```python
# execute_batch() 中调用 _wrap_with_docker_exec_b64 时传入 env_vars
env_vars = config.get("container_env", {})
wrapped_cmd = _wrap_with_docker_exec_b64(docker_container, watchdog_script, env_vars)
```

---

### 2.2 classify_error.py

**修改：timeout → ignored**

```python
# 当前
if "Timeout" in failure_msg or "timeout" in failure_msg:
    return ("retriable_error", "timeout")

# 修改为
if "Timeout" in failure_msg or "timeout" in failure_msg:
    return ("ignored", "timeout")

# OOM 保持 retriable_error（唯一）
if any(tok in failure_msg_lower for tok in _OOM_TOKENS):
    return ("retriable_error", "oom")
```

---

### 2.3 hermes_runner.py (修复 S3)

**问题：** terminal-workflow SKILL.md 调用 `validate_required_config(cfg)` 未传 `channel="linear"`

**修复：**

```python
# terminal-workflow SKILL.md §Startup step 2
# 当前：Validate with hermes_runner.validate_required_config(cfg).
# 修改：Validate with hermes_runner.validate_required_config(cfg, channel="linear").
```

---

### 2.4 failure-handler/SKILL.md

**更新处理范围：**

```markdown
## 处理范围（v5.1 更新）

Failure-handler 只处理：
- `failed` 状态（AssertionError）
- `version` error 类型

以下状态/类型直接 ignored，不进入 Stage 4：
- timeout, resource, dependency, download_error, network, collection, other

### filter_processable() 实现

```python
def filter_processable(tests):
    return [t for t in tests if 
            t["status"] == "failed" or 
            (t["status"] == "error" and t.get("error_type") == "version")]
```
```

---

## 3. 配置文件修复

### 3.1 workflow.e2e.yaml

```yaml
container_env:
  VLLM_ASSETS_CACHE: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
  HF_HOME: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
  HF_HUB_OFFLINE: 1
  HF_HUB_CACHE: /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub
```

### 3.2 workflow.hermes.e2e.yaml

同步补全相同环境变量。

### 3.3 .agents/workflow.yaml (修复 S7)

```yaml
# 当前注释说"默认关闭"但值是 enabled: true
kanban:
  enabled: false  # 改为 false，与注释一致
```

---

## 4. 文档和孤儿清理

### 4.1 README 修复 (P1)

```markdown
# tasks/ut/README.md
# 当前：加载 ut/workflow skill
# 修改：加载 ut/terminal-workflow skill
```

### 4.2 删除孤儿脚本 (S5)

```bash
# tasks/ut/scripts/start_ut_workflow.py - 引用不存在的 run_workflow.py
rm tasks/ut/scripts/start_ut_workflow.py
```

---

## 5. 生产环境检查清单

### 5.1 Profile Distribution

- 验证 `skills/ut/shared/distribution.py` 是否包含最新修改
- 生产 profile 路径：`tasks/ut/deployment/test/profiles/ut-supervisor/`

### 5.2 Manifest 更新脚本

- `skills/ut/manifest-updater/scripts/merge_batch_manifests.py` 存在（56be3d0）
- 验证功能：合并多个 batch_results.json 到原始 manifest.json

### 5.3 环境变量检查

生产测试前验证容器内：
```bash
echo $VLLM_ASSETS_CACHE
echo $HF_HOME
echo $HF_HUB_OFFLINE
echo $HF_HUB_CACHE
```

---

## 6. 测试验证

### 单元测试

```bash
python -m pytest tests/ut/unit/ -q
# 预期：368 passed, 0 failed
```

### 集成测试

```bash
# L1 烟雾测试
python tests/ut/integration/run_linear_channel.py --workflow-yaml tests/ut/integration/fixtures/workflow.l1.yaml

# E2E 验证测试
python tests/ut/integration/run_linear_channel.py --workflow-yaml tests/ut/integration/fixtures/workflow.e2e.yaml
```

---

## 7. 预期影响

| 维度 | 影响 |
|---|---|
| retry 资源消耗 | 减少（timeout/resource 不重试） |
| 人工介入工作量 | 增加（更多 ignored 需人工分析） |
| 审计能力 | 保持（dependency_stall 分类器结果记录） |
| auto-fix commit 数量 | 减少（只有 failed/version 进 Stage 4） |

---

## 附录：代码审查报告关键发现

| ID | 优先级 | 问题 | 本次处理 |
|---|---|---|---|
| P1 | 🔴 P0 | README 引用 ut/workflow 不存在 | ✅ 一并修复 |
| S3 | 🔴 P0 | validate_required_config 未传 channel | ✅ 一并修复 |
| S5 | 🔴 P0 | start_ut_workflow.py 引用不存在文件 | ✅ 删除孤儿 |
| S7 | 🟠 P1 | workflow.yaml 注释与值矛盾 | ✅ 一并修复 |
| S1/S2 | 🟠 P1 | loop-core SKILL.md-only vs run_linear_loop.py 存在 | ⏳ 后续重构 |
| S4/S8 | 🟠 P1 | gateway/hermes_runner 位置混乱 | ⏳ 后续重构 |

---

*Design approved: 2026-06-28*