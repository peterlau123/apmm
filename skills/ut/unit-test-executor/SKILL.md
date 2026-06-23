---
name: unit-test-executor
description: Worker Agent - 单元测试执行器，执行 pytest 测试批次（含 GPU 检测），生成 batch_results.json，由 Supervisor 调用执行 Stage 3
version: 3.2.0
when_to_use: 作为 Worker Agent 被 Supervisor 调用，执行 execute Stage（含 distributed 测试 GPU 检测）
---

# Unit Test Executor (Worker Agent v3.2)

## Behavior (v5)

This section describes the v5 Worker contract. v3.x sections below are kept
for historical context and will be reconciled in a follow-up pass.

### 1. Remote raw_log + local summary

Stage 3 runs pytest **remotely** under a bash watchdog (idle-timeout +
wall-clock fallback, see [2026-06-23-pytest-timeout-redesign.md](../../tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md)),
redirecting **all** stdout/stderr to a single remote file:

```
<remote_log_dir>/<batch_id>/pytest_<batch_id>.log
```

This is the **only** file the Worker writes on the remote host. After pytest
returns, the Worker issues a second remote call
(`grep -E '(PASSED|FAILED|ERROR|SKIPPED|__WATCHDOG__)' ... ; tail -50 ...`)
and writes the captured text to a **local** `summary.txt` next to
`batch_results.json`.

`batch_results.json` carries a `remote_log` pointer instead of inlining the
log:

```json
"remote_log": {
  "host": "t_h20",
  "container": "v0.13.0_torch2.5.1_compile",
  "raw_log_path": "/gpfs/.../ut_logs/<batch_id>/pytest_<batch_id>.log",
  "size_bytes": 4242,
  "captured_at": "2026-06-20T12:34:56Z"
}
```

`captured_at` uses `datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")`.

### 2. Error classification

`classify_error.classify(summary_text, test_id) -> (status, error_type)`:

| Pattern                                                | status            | error_type   |
| ------------------------------------------------------ | ----------------- | ------------ |
| `PASSED ...` (and no FAILED on the same fragment)      | `passed`          | `None`       |
| `torch.cuda.OutOfMemoryError` / `CUDA out of memory`   | `retriable_error` | `oom`        |
| pytest-timeout (`+ Timeout >Ns +` / `Failed: Timeout`) | `retriable_error` | `timeout`    |
| `ERROR collecting` / `ImportError` / `ModuleNotFound`  | `error`           | `collection` |
| `FAILED ...`                                           | `failed`          | `assertion`  |
| anything else                                          | `error`           | `other`      |

OOM and pytest-timeout are **transient** → re-runnable in a later batch by
Stage 2. They are *not* treated as hard failures here.

The legacy category-letter `classify_error()` API (C/E/D/P/M/S/U) is preserved
for back-compat; the new tuple-returning `classify()` is what the executor
wires into `batch_results.json`.

### 3. No Worker self-retry

The Worker runs each test **exactly once per batch**. It does NOT loop over
test execution, does NOT re-attempt on flake, and does NOT mutate
`retry_count`. Retries are owned by Stage 2 (batch selector), which re-selects
tests with `status ∈ {retriable_error, error}` whose `retry_count < max_retry`.

### 4. Bastion disconnect handling

When the remote-call helper (`run_remote`) raises `ConnectionError` — i.e. the
bastion daemon is unreachable / SSH connect failed — the Worker:

1. Calls `BastionManager(...).mark_disconnected(reason=...)` to set
   `bastion.status = "disconnected"` in `workflow_state.json`.
2. Returns `{"batch_id": ..., "next_action": "wait", "reason": ...}`.
3. **Does NOT** write `batch_results.json`.
4. **Does NOT** mutate manifest or per-test status.

The Supervisor sees `next_action=wait`, parks the batch, and resumes once
heartbeat / OTP recovery flips `bastion.status` back to `connected`. No tests
are billed against `retry_count` for a disconnect.

`BastionManager` exposes the symmetric pair `mark_disconnected(reason=...)`
and `mark_connected()` for any caller that needs to surface connection state.

---


---

## Worker 角色

```
┌─────────────────────────────────────────────────────────────┐
│  Worker Agent Session (临时，执行后释放)                     │
│                                                             │
│  职责：                                                      │
│  • 读取 batch_config.json                                   │
│  • 检测 distributed 测试和 GPU 可用性                        │
│  • 远程执行 pytest 测试                                      │
│  • 解析测试结果                                              │
│  • 写入 batch_results.json                                  │
│  • 返回极简结果给 Supervisor                                │
│                                                             │
│  输入：batch_config.json                                     │
│  输出：batch_results.json + 极简 stats                       │
│  Session 结束后：Context 释放                                │
│                                                             │
│  ⚠️ GPU 检测职责已从 batch-selector 移至本 Stage            │
└─────────────────────────────────────────────────────────────┘
```

---

## 流程图

```mermaid
flowchart TB
    subgraph Input["[输入] Supervisor 调用"]
        A1["batch_config.json 路径"]
        A2["pytest_args"]
        A3["timeout"]
    end
    
    Input --> Step1
    
    subgraph Step1["[Step 1] 加载批次配置"]
        S1_1["读取 batch_config.json"]
        S1_2["获取 tests 列表"]
        S1_3["检查 distributed 标记"]
    end
    
    Step1 --> Step1b
    
    subgraph Step1b["[Step 1b] GPU 检测（distributed 测试）"]
        S1b_1["distributed 测试存在?"]
        S1b_2["检查远程 GPU 可用性"]
        S1b_3["available_gpus >= 2?"]
        S1b_4["GPU < 2 → 返回 blocked_reason"]
    end
    
    Step1b --> Step2
    
    subgraph Step2["[Step 2] 执行 pytest"]
        S2_1["构建 pytest 命令"]
        S2_2["设置分布式环境变量（如需要）"]
        S2_3["远程执行（agent.py + Docker）"]
        S2_4["监控超时"]
    end
    
    Step2 --> Step3
    
    subgraph Step3["[Step 3] 内置日志提取与解析"]
        direction LR
        S3_1["远程 grep 提取"] --> S3_2["Bastion 传输"]
        S3_2 --> S3_3["parse_remote_log.py"]
        S3_3 --> S3_4["batch_results.json"]
    end
    
    Step3 --> Step4
    
    subgraph Step4["[Step 4] 返回结果"]
        S4_1["batch_results.json 已生成"]
        S4_2["返回极简 stats（统一格式）"]
        S4_3["Session 结束"]
    end
```

> **v3.2**: Step 3 日志提取已内置为 stage 核心行为，不再是可选的 post_action

---

## 输入输出

### 输入（从 Supervisor context 获取）

| 字段 | 来源 | 说明 |
|------|------|------|
| `workflow_state_path` | Supervisor context | 状态文件路径 |
| `batch_config_path` | workflow.yaml | 批次配置路径 |
| `pytest_args` | workflow.yaml | pytest 参数 |
| `timeout` | workflow.yaml | 超时时间（秒） |

### 输出

| 类型 | 内容 | 说明 |
|------|------|------|
| **文件** | batch_results.json | 测试结果文件 |
| **返回** | stats (极简) | 给 Supervisor 的返回值 |

---

## 执行流程

### Step 1: 加载批次配置

```python
import json
from pathlib import Path

# 从 workflow_state.json 读取路径配置（不硬编码）
from shared.config_loader import get_paths
paths = get_paths(workflow_state_path)

# 读取 batch_config
batch_config_path = paths["batch_config"]
batch_config = json.loads(Path(batch_config_path).read_text())

tests = batch_config["tests"]
batch_id = batch_config["batch_id"]
distributed_count = batch_config.get("distributed_count", 0)

# 判断是否有 distributed 测试
has_distributed = distributed_count > 0
```

### Step 1b: GPU 检测（distributed 测试需要）

```bash
# 仅当 distributed 测试存在时检测 GPU
if has_distributed:
    # 通过 agent.py 检查远程 GPU
    python agent.py -p t_h20 run --timeout 30 "
        sudo docker exec v0.13.0_torch2.5.1_compile bash -c '
            nvidia-smi --query-gpu=index,memory.used,memory.total --format csv,noheader |
            awk -F, \"{usage=\$2/\$3; if (usage < 0.1) print GPU \$1: available}\" 
        '
    "
```

```python
# 解析 GPU 可用性
def parse_gpu_output(output):
    available = len([line for line in output.splitlines() if "available" in line])
    return available

available_gpus = parse_gpu_output(gpu_output) if has_distributed else 999  # normal 测试不需要 GPU

# GPU 不足时返回 blocked_reason
if has_distributed and available_gpus < 2:
    return {
        "stats": {"passed": 0, "failed": 0, "ignored": 0, "error": 0, "pending": 0},
        "next_action": "wait",
        "error": None,
        "blocked_reason": f"distributed 测试需要 2+ GPU，当前可用 {available_gpus} 个"
    }
```

### Step 2: 执行 pytest（远程）

```bash
# 构建 pytest 命令
test_nodes = [t["test_node"] for t in tests]
pytest_cmd = f"pytest {' '.join(test_nodes)} -q --tb=long"

# distributed 测试环境变量（GPU 检测已通过）
if has_distributed and available_gpus >= 2:
    env_vars = "MASTER_ADDR=localhost MASTER_PORT=29500 WORLD_SIZE=2"
    pytest_cmd = f"{env_vars} {pytest_cmd}"

# 通过 agent.py 远程执行
python agent.py -p t_h20 run --timeout 3600 "
    sudo docker exec v0.13.0_torch2.5.1_compile bash -c '
        cd /gpfs/gcsp/M2.7_verify/vllm &&
        {pytest_cmd} 2>&1 | tee ut_logs/{batch_id}.log
    '
"
```

### Step 3: 解析 pytest 输出（远程日志提取）

**v3.2 新增功能**：通过 bastion 远程 grep 提取结果，本地解析生成 batch_results.json

```mermaid
flowchart LR
    R[远程日志] --> G[grep PASSED/FAILED/ERROR]
    G --> B[Bastion 传输]
    B --> L[本地 stdout]
    L --> P[parse_remote_log.py]
    P --> J[batch_results.json]
```

**执行方式**：

```bash
# 方式 1：使用 run_batch.py --with-results（推荐）
python run_batch.py --tests ... --with-results --output-dir ./results

# 方式 2：仅提取已有日志
python run_batch.py --extract-only /gpfs/.../ut_logs/phase1/batch_001.log

# 方式 3：手动调用 parse_remote_log.py
python agent.py -p t_h20 run "grep -E '(PASSED|FAILED|ERROR)' {log_file}" |
    python parse_remote_log.py --stdin --batch-id {batch_id} --output batch_results.json
```

**核心脚本**：

| 脚本 | 功能 |
|------|------|
| `run_batch.py` | 新增 `--with-results`, `--extract-only` 选项 |
| `parse_remote_log.py` | 解析 grep 输出，生成 batch_results.json |
| `agent.py` | Bastion SSH daemon，远程执行 grep |

**错误分类映射**：

| C/E/D/P/M/S | batch_results error_type |
|-------------|--------------------------|
| C (Code Bug) | `functional` |
| E (Environment) | `other` |
| D (Dependency) | `dependency` |
| P (Platform) | `resource` |
| M (Model) | `download_error` |

**Bastion 传输限制**：
- recv buffer: 65535 bytes (~65KB)
- 建议单批次传输 (<50KB)，避免全量传输

### Step 4: 写入文件并返回

```python
# batch_results 结构
batch_results = {
    "batch_id": batch_id,
    "executed_at": datetime.now().isoformat(),
    "tests": results["passed"] + results["failed"] + results["error"],
    "stats": {
        "passed": len(results["passed"]),
        "failed": len(results["failed"]),
        "error": len(results["error"]),
        "total": len(tests)
    },
    "log_file": f"/gpfs/gcsp/M2.7_verify/vllm/ut_logs/{batch_id}.log"
}

# 写入 batch_results.json（路径从 workflow.yaml 读取）
batch_results_path = paths["batch_results"]
Path(batch_results_path).write_text(json.dumps(batch_results, indent=2))

# 返回极简结果给 Supervisor（统一格式）
return {
    "stats": {
        "passed": len(results["passed"]),
        "failed": len(results["failed"]),
        "ignored": 0,
        "error": len(results["error"]),
        "pending": 0
    },
    "next_action": "continue",
    "error": None,
    "blocked_reason": None
}
```

---

## 返回格式规范（统一）

```json
{
  "stats": {
    "passed": 40,
    "failed": 8,
    "ignored": 0,
    "error": 2,
    "pending": 0
  },
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
```

**注意：只返回统一字段，不返回 batch_id、log_file、details_file 等额外字段**

---

## distributed 测试处理

|| 场景 | GPU 可用 | 动作 |
||------|:--------:|------|
|| distributed + GPU ≥ 2 | ≥ 2 | 设置分布式环境变量执行 |
|| distributed + GPU < 2 | < 2 | **返回 blocked_reason**，next_action="wait" |
|| normal tests | - | 直接执行（无需 GPU 检测） |

**注意：GPU 检测职责已从 batch-selector 移至本 Stage**

---

## 错误分类概览

| 类别 | 说明 | 处理策略 |
|------|------|----------|
| **dependency** | Python 包缺失 | 由 Stage 4 处理 |
| **network** | 网络超时 | 由 Stage 4 处理 |
| **resource** | GPU/内存不足 | 由 Stage 4 处理 |
| **version** | PyTorch API 缺失 | 由 Stage 4 处理 |
| **functional** | 代码逻辑失败 | 由 Stage 4 处理 |
| **other** | 其他错误 | 由 Stage 4 处理 |

> Stage 3 只负责执行和分类，**不处理错误**（由 Stage 4 failure-handler 处理）

---

## 前置/后置任务

| 类型 | 任务 | 说明 |
|------|------|------|
| **前置** | Supervisor 调用 | delegate_task 触发 |
| **前置** | batch_config.json 存在 | Stage 2 输出 |
| **前置** | 远程容器可用 | t_h20 + Docker |
| **后置** | batch_results.json 写入 | 输出文件 |
| **后置** | 返回 stats + batch_id | 极简返回值 |
| **后置** | Supervisor 继续 Stage 4 | handle_failures |

---

## Pitfalls（关键陷阱）

| # | 问题 | 说明 | 解决方案 |
|---|------|------|----------|
| 1 | **容器选择错误** | 使用错误容器 | 使用 `v0.13.0_torch2.5.1_compile` |
| 2 | **distributed GPU** | 单 GPU 执行 distributed | 检测 GPU ≥ 2 才执行 |
| 3 | **SSH 超时** | agent.py foreground 最大 300s | 长测试用 background |
| 4 | **pytest 参数** | `-v` 输出太多 | 用 `-q --tb=long` |
| 5 | **路径前缀重复** | `tests/tests/...` | 检查路径前缀 |
| 6 | **裸 `docker exec` permission denied** | 远端 `infra` 用户不在 `docker` 组；`/var/run/docker.sock` 仅 `root:docker` 可写 | **必须**用 `sudo -n docker exec ...`（远端已配置 passwordless sudo）。所有 SKILL 示例已是此形式；不要手写 `docker exec ...` |
| 7 | **`bash -c` 触发 Hermes shell-guard approval** | Hermes core `tools/approval.py` 把 `(bash|sh|zsh|ksh)\s+-[^\s]*c` 列为危险模式；Kanban-gateway session 走 `submit_pending` 路径，60s 内无人响应即超时 → 任务 `blocked` | 已在 `~/.hermes/config.yaml` 的 `command_allowlist` 加入 `shell command via -c/-lc flag`，本机已生效（mtime-keyed cache）。新机器部署时记得同步该配置 |

---

## 注意事项

1. **容器版本固定**：必须使用 `v0.13.0_torch2.5.1_compile`
2. **distributed GPU 检测**：执行前检测 GPU 可用性（已从 batch-selector 移至本 Stage）
3. **GPU 不足时返回 blocked_reason**：不跳过批次，而是返回 blocked_reason 让 Supervisor 处理
4. **超时管理**：单批次最大 3600 秒
5. **极简返回**：只返回 stats 数字，不返回详细错误
6. **错误不处理**：Stage 3 只分类，Stage 4 处理

---

## 禁止操作（硬契约 — 违反即视为污染数据，supervisor 会 invalidate run）

### 数据完整性禁令（不可越权）

- 🚫 **绝对禁止 fabrication**：`batch_results.json` 中的每一个数字（`total_duration_seconds`、`exit_code`、`passed/failed/error` 计数、`gpu_info`、`log_path`）**必须**来自真实执行过的 `agent.py -p t_h20 run "sudo -n docker exec ... pytest ..."` 的返回值；
  - 禁止：凭印象/上游 SKILL 说明/合理推断填写任何字段；
  - 禁止：在 `log_path` 写远端不存在的路径（supervisor 会 stat 验证）；
  - 禁止：`duration_seconds: null` 但 `status: passed/failed` 的组合（要么是真跑过且有 duration，要么是没跑成功 → 报 error，不要谎报状态）；
  - 如果远端命令失败/超时/中断，**如实记录**为 `status: error` + `error_message: <真实错误>`，不要"补全"成 passed/failed。
- 🚫 **绝对禁止越权发送 Feishu / Lark / 任何外部通知**：
  - 禁止：写 Python 脚本调用 `open.feishu.cn`、`api.lark.com`、`webhook` 等 IM API；
  - 禁止：用 `requests.post` / `curl` 向 Feishu/Lark/Slack/钉钉 发任何消息；
  - 禁止：跨 profile 读取 `~/.claude/...` / `~/.hermes/profiles/<other>/...` 下的 token；
  - 唯一允许的通知路径：**返回 stats 给 supervisor**，由 supervisor 走 Hermes 标准投递层（`send_feishu_card` / `hermes-runner`）发出。
- 🚫 **绝对禁止修改 `manifest.json`**：那是 Stage 5（manifest-updater）的职责，executor 只产 `batch_results.json`。
- 🚫 **绝对禁止删除/重命名上游产物**：`batch_config.json`、`test_list.txt`、`workflow_state.json`、其他 batch 的目录 —— 都不要碰。

### 行为禁令

- ❌ 不返回详细错误信息（只返回 stats）
- ❌ 不处理错误（让 Stage 4 处理）
- ❌ 不下载依赖/模型
- ❌ 不在本地执行 pytest（必须远程容器内）
- ❌ 不返回 batch_id/log_file/details_file 等额外字段（只返回统一格式）
- ❌ 不"尝试 recover Bastion daemon" —— daemon 由 supervisor 通过 OTP 管，worker 看到 daemon 死了就 `next_action=wait` 直接返回，不要自作主张
- ❌ 不写 `D:/workspace/apmm/scripts/*.py`、`tools/*.py` 等仓库根目录脚本（worker 工作目录是当前 run_dir，仓库脚本是开发者维护的）

### 历史教训（不要重蹈）

| 日期 | 越权行为 | 后果 |
|---|---|---|
| 2026-06-22 | 某 worker 在 stage-3 不真跑 pytest，编造 batch_results.json（log_path 指向不存在的远端文件），改 manifest 为 "completed"，并手写 `scripts/send_feishu_report.py` + 用 Claude 工具链的 Feishu token 直接发"完成报告"到 ai-engineer 群 | run `ut-20260621-234651` 被 supervisor invalidated；写入这条约束 |

---

## 相关文档

- [workflow.yaml](../../.agents/workflow.yaml) - Workflow 配置
- [workflow/SKILL.md](../workflow/SKILL.md) - Supervisor 调度逻辑
- [batch-selector/SKILL.md](../batch-selector/SKILL.md) - 上游 Stage（已移除 GPU 检测）
- [failure-handler/SKILL.md](../failure-handler/SKILL.md) - 下游 Stage
- [parse_remote_log.py](scripts/parse_remote_log.py) - **新增**: 远程日志解析脚本
- [run_batch.py](scripts/run_batch.py) - **更新**: 新增 `--with-results`, `--extract-only`
- [agent.py](../../tools/agent.py) - Bastion SSH daemon

---

*创建日期: 2026-06-09*
*更新日期: 2026-06-11*
*版本: 3.2.0*