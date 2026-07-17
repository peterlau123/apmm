# Pytest Timeout Redesign — idle-based watchdog + LLM dependency stall classifier

**Date**: 2026-06-23
**Status**: 📐 Design (this document); implementation pending
**注意：** `.agents/workflow.yaml`已废弃（2026-06-29），配置机制已迁移至`tasks/ut/deployment/production/config/`模板库 + `runs/ut-{timestamp}/`副本机制。
**Driver**: 2026-06-23 grilling session — failure-mode conflation (issue C)
**Related**: [2026-06-23-l4-postmortem-and-fixes.md](../incidents/2026-06-23-l4-postmortem-and-fixes.md) (M3 done; not the same scope)
**Scope**: UT 子系统单体范畴（仅 `skills/ut/unit-test-executor` + `skills/ut/failure-handler` + workflow yaml fixtures）

---

## 0. TL;DR

把 batch pytest 的 **600s wall-clock timeout** 替换为 **idle-timeout (120s) + wall-clock 兜底 (600s) 双值机制**，并把 timeout 类失败的「真因分类」从硬编码 grep 改为 **Stage 4 LLM 判读** + 固化 schema。

主要修复目标（issue C 失败模式不分流）：

| 真因 | 旧行为 | 新行为 |
|---|---|---|
| Dep download stall（HF / pip 卡住）| 600s × 3 retry = 30 min 浪费 → 最终 ignored | LLM 看 log → 直接 ignored，跳过 retry |
| Pytest deadlock | 600s × 3 retry = 30 min | idle 120s × 3 retry = 6 min（成本压低后保留 retry）|
| GPU OOM hang | 600s × 3 retry，每次重压同样的 OOM | retry 不动；idle 把单次成本压低 |
| SSH transport idle drop | 600s × 3 retry | 同上；watchdog 杀掉后下次 ensure_connected 恢复 |
| LLM 看不懂 / JSON 不合 schema | n/a | `classification=unknown` → 保守 ignored |

不动的：batch 级超时粒度（一次 SSH 一个 batch 共享预算）、test 类型差异化（idle 模型消解了需求）、`raw_log` 数据契约（仅改文件名）。

---

## 1. Context

### 1.1 现状（来自 grilling）

| 项 | 值 | 源 |
|---|---|---|
| Stage 3 远程 pytest timeout | 600s (wall-clock) | `execute_batch.py:182` default; `workflow.l4.yaml:213` |
| 本地 paramiko 兜底 | `pytest_timeout + 60s` = 660s | `execute_batch.py:81` |
| Stage 4 failure-handler Agent timeout | 900s | yaml |
| Timeout 触发处理 | `subprocess.TimeoutExpired` → returncode=-1/124 → `error_type="timeout"` → schema 归 `retriable_error` → retry 上限 3 次 → 3 次都超 → ignored | execute_batch + manifest schema + failure-handler |
| Batch 粒度 | 一次 SSH 调用整 batch 共享 600s（`batch_size=3` → 平均 200s/test）| `execute_batch.py:191-205` |
| 远端 log 文件 | `<remote_log_dir>/<batch_id>/raw_log.txt` | `execute_batch.py:187` |

### 1.2 根问题（issue C）

所有"远端 600s 没响应"被映射到同一个 error_type `timeout`，下游无法分流：
- HF 模型下载卡 599s → 第 3 次 retry 还是卡（网络条件没变）→ 30 min 烧掉
- pytest 死锁 → retry 第 2 次大概率绕过（环境变了）→ 但浪费第一次的 600s
- OOM hang → retry 重压同样 OOM → 浪费 3 × 600s
- 真实超时（test 本身慢）→ retry 还是慢 → 浪费

且**当 batch 内某一个 test 卡死，整 batch 一起被杀**，3 个 test 都被标 `timeout`，无法定位真凶（grilling Q1.1 揭露的副作用）。

---

## 2. 设计决定（grilling 结果）

| # | 主题 | 决定 |
|---|---|---|
| D1 | Driver | (C) 失败模式分流不准；不做 (A) 调阈值 / (B) 改 retry 次数 / (D) 预防性 |
| D2 | Batch 粒度 | **保留**（不改成 per-test）|
| D3 | Idle vs wall-clock | **双值**：`pytest_idle_timeout=120s` 主，`timeout=600s` wall-clock 兜底；任一触发 → kill -9 → returncode=124 |
| D4 | Watchdog 实现 | **远端 bash watchdog**（单 SSH session 内）— pytest 后台跑 + 监 log mtime + 双条件 kill |
| D5 | Log 文件名 | `<remote_log_dir>/<batch_id>/pytest_<batch_id>.log`（替代 `raw_log.txt`）|
| D6 | LLM 判读位置 | **Stage 4 failure-handler**（Stage 3 只标 raw `error_type=timeout`）|
| D7 | LLM 输出 schema | 三值 + 强制 evidence：`classification ∈ {"dep_stall","not_dep_stall","unknown"}` + `evidence: str` + `dependency_hint: str?` |
| D8 | unknown 语义 | `unknown → ignored`（保守优先，与 dep_stall 同款 reason）|
| D9 | Schema 物理文件 | `skills/ut/ut_common/dependency_stall_schema.json`（JSON Schema Draft-07）|
| D10 | Prompt 物理位置 | `skills/ut/failure-handler/SKILL.md §X`（固化模板，agent 调用时不重写）|
| D11 | LLM JSON 实例落盘 | `handled_tests.json` 的 `resolution.dependency_classification`（不写 manifest）|
| D12 | Test 类型差异化 timeout | **不做**（idle 模型消解需求）|
| D13 | Deadlock 特殊处理 | **不做**（idle 把成本从 30 min 压到 6 min 后，无差别 retry 可接受）|
| D14 | Dep miss（显式）| 保持 M2 Option E 行为不变（fixer 直接 ignored，本设计只补"download stall"这一类）|

---

## 3. 行为表

| timeout 真因 | log 末尾 LLM 看到 | classification | final_status | ignored_reason / 行为 |
|---|---|---|---|---|
| 大模型 HF 下载卡住 | `Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]` | `dep_stall` | `ignored` | `依赖未就绪需人工处理: meta-llama/Llama-3.2-1B-Instruct` |
| pip 安装 hang | `Collecting mteb-1.0.0 ...` | `dep_stall` | `ignored` | `依赖未就绪需人工处理: mteb` |
| pytest deadlock | `test_foo: waiting on mutex ...` 或纯静默 | `not_dep_stall` | `retriable_error` → retry ≤ 3 → 3 次后 ignored | — |
| GPU OOM hang | `CUDA out of memory` | `not_dep_stall` | `retriable_error` → retry | — |
| SSH transport idle drop | 末尾正常 PASSED 行（之后无新内容）| `not_dep_stall` 或 `unknown` | retry / ignored | — |
| LLM JSON parse 失败 / schema mismatch / 缺 evidence | fallback in classifier code | `unknown` | `ignored` | `分类不明 (LLM 未识别 / schema mismatch); 末尾日志: <last-line>` |
| Watchdog 124 但 log 末尾全 PASSED | 罕见（idle 误杀）| `not_dep_stall` | retry | — |

---

## 4. 远端 watchdog bash 模板（固化）

写在 `execute_batch.py` 里作为字符串常量；agent **不允许**在 prompt 中重写。

```bash
# Variables injected by execute_batch.py:
#   BATCH_ID, LOG_PATH, IDLE_TIMEOUT (sec), WALL_TIMEOUT (sec), PYTEST_FULL_CMD
mkdir -p "$(dirname "$LOG_PATH")"
$PYTEST_FULL_CMD > "$LOG_PATH" 2>&1 &
PID=$!
START=$(date +%s)
while kill -0 $PID 2>/dev/null; do
    sleep 10
    NOW=$(date +%s)
    # wall-clock 兜底
    if [ $((NOW - START)) -gt $WALL_TIMEOUT ]; then
        kill -9 $PID
        echo "__WATCHDOG__: wall_clock_exceeded after $((NOW-START))s" >> "$LOG_PATH"
        exit 124
    fi
    # idle 检测
    if [ -f "$LOG_PATH" ]; then
        LAST_MTIME=$(stat -c %Y "$LOG_PATH")
        if [ $((NOW - LAST_MTIME)) -gt $IDLE_TIMEOUT ]; then
            kill -9 $PID
            echo "__WATCHDOG__: idle_exceeded $((NOW-LAST_MTIME))s (no log activity)" >> "$LOG_PATH"
            exit 124
        fi
    fi
done
wait $PID
exit $?
```

- 心跳粒度 10s（小于 idle 阈值 120s 的 1/12，足以捕获）。
- `__WATCHDOG__` 哨兵字符串落入 log 末尾，LLM 判读时一眼能看到（同时也给 evidence 字段提供锚点）。
- 远端必须有 `stat -c %Y`（GNU coreutils 标准；vLLM 测试容器是 Ubuntu，没问题）。

---

## 5. LLM 调用 contract

### 5.1 JSON Schema（D9）

`skills/ut/ut_common/dependency_stall_schema.json`：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Dependency Stall Classification",
  "type": "object",
  "required": ["classification", "evidence"],
  "additionalProperties": false,
  "properties": {
    "classification": {
      "type": "string",
      "enum": ["dep_stall", "not_dep_stall", "unknown"]
    },
    "evidence": {
      "type": "string",
      "minLength": 1,
      "description": "A single line quoted verbatim from the log末尾 to support the classification."
    },
    "dependency_hint": {
      "type": ["string", "null"],
      "description": "Specific resource name if dep_stall (model id / pip pkg / etc); null otherwise."
    }
  }
}
```

### 5.2 固化 prompt（D10）

`skills/ut/failure-handler/SKILL.md §X`：

```markdown
## §X. Dependency-stall classifier (固化 prompt — 不可在调用时改写)

调用前置：本 batch 在 Stage 3 已被 watchdog kill (returncode=124, error_type=timeout)。
现在需要判断 timeout 的真因是不是「依赖资源未就绪」。

输入: log_tail_text (远端 pytest_<batch_id>.log 末尾 200 行 + grep 摘要)
输出契约: skills/ut/ut_common/dependency_stall_schema.json

Prompt 模板（一字不改地发给 LLM）:

---
以下是一个 pytest batch 因 idle/wall-clock timeout 被 kill 后的日志末尾内容。

判断这次 timeout 的真因，分类为以下三者之一：

1. "dep_stall" — 因「依赖资源未就绪」而 hang，典型证据：
   - HuggingFace 模型下载中（"Downloading", "Fetching", URL 含 huggingface.co）
   - pip install 中（"Collecting", "Downloading .whl"）
   - HF cache miss / auth token 等待
   - 任何形式的「正在等待网络资源到位」

2. "not_dep_stall" — 看不到上述迹象，更像是：
   - 测试代码本身 hang / 死锁
   - GPU OOM / CUDA error
   - SSH transport drop（log 末尾正常 PASSED 后无新内容）
   - 其它非依赖资源类的卡死

3. "unknown" — 看不清属于哪类；判不准时优先选这个（保守）。

输出严格 JSON（无 markdown fence、无前后文）：
{
  "classification": "<dep_stall | not_dep_stall | unknown>",
  "evidence": "<引用 log 里一行原文作为依据>",
  "dependency_hint": "<具体资源名，如 'meta-llama/Llama-3.2-1B' 或 'mteb' 包名；非 dep_stall 时为 null>"
}

evidence 必填且必须来自 log；不允许编造或泛述。
---
```

### 5.3 调用代码 + fallback（D7, D8）

`skills/ut/failure-handler/scripts/classify_dependency_stall.py`：

```python
def classify(log_tail_text: str, llm_invoker) -> dict:
    """Returns a dict matching dependency_stall_schema.json.
    On any failure (LLM down, JSON parse error, schema mismatch),
    returns the canonical unknown fallback."""
    try:
        raw = llm_invoker(prompt_template, log_tail_text)
        parsed = json.loads(raw)
        jsonschema.validate(parsed, schema)
        return parsed
    except (json.JSONDecodeError, jsonschema.ValidationError, Exception) as e:
        return {
            "classification": "unknown",
            "evidence": (log_tail_text.splitlines() or ["<empty log>"])[-1][:200],
            "dependency_hint": None,
            "_fallback_reason": str(e)[:100],  # debugging aid, not in schema
        }
```

### 5.4 ignored_reason 拼装（D11）

由 `generate_handled_manifest.py` 在写 `handled_tests.json` 时构造，**不让 LLM 出 reason**：

```python
if cls == "dep_stall":
    reason = f"依赖未就绪需人工处理: {dep_hint or evidence}"
elif cls == "unknown":
    reason = f"分类不明 (LLM 未识别 / schema mismatch); 末尾日志: {evidence}"
else:  # not_dep_stall
    reason = None  # 不 ignored，走 retry
```

---

## 6. 数据流（端到端）

```
Stage 3 execute_batch:
  写远端 pytest_<batch_id>.log
  跑 watchdog bash (单 SSH)
  → watchdog 触发 → returncode=124
  本地 batch_results.json 标 error_type=timeout（行为不变）

Stage 4 failure-handler:
  for each test with error_type=timeout:
    pull log 末尾 200 行 (单次 SSH grep+tail)
    → classify_dependency_stall.classify(log_tail)
    → 返回 dict {classification, evidence, dependency_hint}
    → handled_tests.json 写入:
       resolution.dependency_classification = dict
       final_status = "ignored" if cls in ("dep_stall","unknown") else 进 retry
       ignored_reason = 按 cls 拼

Stage 5 manifest-updater:
  读 handled_tests.json → 更新 manifest.json
  manifest 只看 final_status + ignored_reason
  dependency_classification 字段不进 manifest（避免污染）
```

---

## 7. handled_tests.json 字段扩展

新增 `resolution.dependency_classification` 子结构。完整 entry 示例：

```json
{
  "id": 1,
  "test_node": "tests/models/test_llama.py::test_load_3.2_1b",
  "classification": {"type": "timeout", "subtype": "wall_clock"},
  "resolution": {
    "status": "ignored",
    "action": "skip",
    "dependency_classification": {
      "classification": "dep_stall",
      "evidence": "Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]",
      "dependency_hint": "meta-llama/Llama-3.2-1B-Instruct"
    }
  },
  "final_status": "ignored",
  "ignored_reason": "依赖未就绪需人工处理: meta-llama/Llama-3.2-1B-Instruct",
  "fix_applied": false
}
```

manifest.json schema 不变（已有 `final_status` + `ignored_reason` 即够用）。

---

## 8. 实施清单

| # | 文件 | 改动 | 类型 |
|---|---|---|---|
| 1 | `skills/ut/unit-test-executor/scripts/execute_batch.py` | log 路径改 `pytest_<batch_id>.log`；远端 bash 改 watchdog 模板（§4）；接收 `pytest_idle_timeout` config | refactor |
| 2 | `skills/ut/unit-test-executor/scripts/execute_batch.py` | 本地 `subprocess.run` timeout 改为 `wall_timeout + 60s`（继续作为绝对兜底）| refactor |
| 3 | `.agents/workflow.yaml` + `tests/ut/integration/fixtures/workflow.l*.yaml` × 5 | 新增 `stages[execute].pytest_idle_timeout: 120`；保留 `timeout: 600` 改语义注释为 wall-clock 兜底 | config |
| 4 | `skills/ut/ut_common/dependency_stall_schema.json` (新) | JSON Schema Draft-07，§5.1 | new |
| 5 | `skills/ut/failure-handler/scripts/classify_dependency_stall.py` (新) | pull log 末尾 → LLM 调用 → jsonschema 校验 → unknown fallback | new |
| 6 | `skills/ut/failure-handler/SKILL.md` | 新增 §X dependency stall classifier 段（§5.2 固化 prompt + schema 引用 + unknown 规则）| docs |
| 7 | `skills/ut/failure-handler/scripts/generate_handled_manifest.py` | timeout 类失败调 classify_dependency_stall；按 classification 决定 final_status；写入 `resolution.dependency_classification` 字段；拼 ignored_reason | feat |
| 8 | `tests/ut/unit/test_dependency_stall_classifier.py` (新) | fixture log × 3（HF 下载 / deadlock / 模糊）+ JSON malformed + schema mismatch case；校验 fallback unknown；校验 ignored_reason 拼装 | test |
| 9 | `tests/ut/unit/test_execute_batch_watchdog.py` (新) | mock remote response，验证 idle 触发 / wall-clock 触发各产生 returncode=124；验证 log 路径命名；验证 watchdog 模板渲染（关键 var 全到位）| test |
| 10 | 本设计文档（已就位）| 决定矩阵 + 行为表 + 实施清单 | docs |

### 8.1 L4 baseline 风险

L4 expected fixture `tests/ut/integration/fixtures/L4_expected.json` 的 AF-2（duration_ms）受 watchdog 行为影响。本次仅 3 个 retry-subset test，且历史 L4 run 均在 ~42 min 内完成（远低于 wall-clock 600s）；watchdog 不会改变它们的终态分布。**建议**：实施完成后先在新 run_dir 跑一次 L4 验证 6/6 PASS，再 commit 本设计的 baseline 更新。

### 8.2 回归测试

| 单测 | 现状 | 改动后 |
|---|---|---|
| `test_otp_resend.py` 等 12 个 OTP 测试 | M3 已落 PASS | 不影响 |
| `test_kanban_board.py` 9 个 | 预存 fail（与本设计无关）| 不动 |
| 其余 250+ 单测 | M3 收尾时全 PASS | 应保持 PASS（execute_batch / failure-handler 改动会触发相关单测更新）|
| 新增 `test_execute_batch_watchdog` + `test_dependency_stall_classifier` | — | 应全 PASS |

---

## 9. 非目标

- **不**做 per-test timeout（batch 粒度保留）
- **不**做 test 类型差异化阈值（idle 模型消解）
- **不**改 retry 次数上限（仍是 max_retry=3）
- **不**改 dep miss（显式 ModuleNotFoundError）的路径（M2 Option E 已 ignored）
- **不**改 manifest.json schema（新字段只挂 handled_tests.json）
- **不**做远端 watchdog 之外的 idle 检测方式（本地轮询 / 流式 stdout 都被 grilling 排除）

---

## 9.1 反复确认：wall-clock 与 idle 的关系

Grilling 复盘中重新审视过的方案，**已拒绝**，记录于此防止重新讨论：

| 方案 | 语义 | 拒绝理由 |
|---|---|---|
| **复合规则**：必须 idle 且 wall 都超才杀 | wall 从独立杀手降级为"等待期" | Case B（test 30s 后死掉）会多等 450s 才杀，违背本设计「快速识别死 test」的初衷 |
| **纯 idle，去掉 wall** | 只看 idle，理论上长 test 不打扰 | idle 检测自身出 bug（mtime 读不到、stat 缺失）时无兜底；wall 还有"释放 SSH session / bastion daemon 资源"的次要作用，不只是杀 test |
| **wall 上调到 1800s** | 给"合法长 test"更多空间 | vLLM batch（batch_size ≤ 3）内合法 test 跑不到 600s 已经被验证；上调无收益但放宽兜底 |

**最终保留**：idle=120s 主，wall=600s 兜底，**独立触发**（任一满足即 kill）。这是双值机制的初心。

---

## 10. 后续

实施 commit 计划（不在本文档范围）：

1. Schema + fixture log + 单测先写好（红灯）
2. classify_dependency_stall.py + SKILL.md prompt（绿灯第一步）
3. execute_batch watchdog 改造 + 单测（绿灯第二步）
4. yaml 配置更新 5 个文件
5. L4 集成跑通验证 6/6 PASS
6. 一次性 commit 或按上述 5 步分阶段 commit

预估总工作量 ~6-8 h。

---

**Sign-off**: 2026-06-23 grilling session, 6 round-trips.
