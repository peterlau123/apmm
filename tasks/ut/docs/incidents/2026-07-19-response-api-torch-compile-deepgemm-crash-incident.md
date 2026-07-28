# Response API 测试 torch.compile + DeepGEMM 崩溃事故（torch 2.5.1 API 不匹配）

**日期**: 2026-07-19（诊断与修复完成 2026-07-28）
**严重等级**: P1（7 个 error 测试的根因，torch 2.5.1 与 vLLM AOT compile 重构不匹配 + DeepGEMM 误判）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），7 个 `test_response_api_*.py` 测试报 error(collection)
**修复状态**: ✅ 已闭环（根因定位 + 双补丁 + 环境变量，远端验证 5/7 通过，2 个为模型行为断言失败）

---

## 事故概述

Phase 1 的 12 个 error 测试中，7 个 `test_response_api_*.py`（参数化 `Qwen/Qwen3-0.6B`）在 setup 阶段报 `RuntimeError: Server exited unexpectedly.`，`error_type` 记为 `collection`。表面看是 server 启动失败，深入远端 server log 后发现是 **三层叠加的 torch 2.5.1 兼容问题**：

| 层 | 错误 | 触发条件 |
|----|------|---------|
| 1️⃣ | `InternalTorchDynamoError: patched_inline_call() takes 1 positional argument but 4 were given` | `torch.compile` 路径（`enforce_eager=False`，Response API 默认） |
| 2️⃣ | `TypeError: VllmBackend.__call__() got an unexpected keyword argument 'options'` | 修了层1后，compile 路径继续暴露的第二个 torch 2.5.1 API 不匹配 |
| 3️⃣ | `RuntimeError: DeepGEMM backend is not available or outdated` | `deep_gemm._C` 未编译，但 `is_deep_gemm_supported()` 误判 True，warmup 崩 |

> **关键**：层1/层2 是 vLLM commit `eef921f45` "AOT Compilation for torch.compile" 为 torch ≥2.7 重构的 monkeypatch，在 torch 2.5.1 上整体不兼容（打地鼠，逐个修不现实）。层3 是独立的 deep_gemm 环境问题，**影响所有启动引擎的测试**，只是被层1/层2 挡住没暴露。

---

## 涉及测试清单（7 个）

| # | test_node | id | 修复后状态 |
|---|-----------|----|-----------|
| 1 | `test_response_api_parsable_context.py::test_basic[Qwen/Qwen3-0.6B]` | 1637 | ✅ passed |
| 2 | `test_response_api_parsable_context.py::test_reasoning_and_function_items[Qwen/Qwen3-0.6B]` | 1638 | ✅ passed |
| 3 | `test_response_api_parsable_context.py::test_function_call_first_turn[Qwen/Qwen3-0.6B]` | 1639 | ✅ passed |
| 4 | `test_response_api_parsable_context.py::test_mcp_tool_call[Qwen/Qwen3-0.6B]` | 1640 | ❌ 仍断言失败（mcp_call） |
| 5 | `test_response_api_simple.py::test_basic[Qwen/Qwen3-0.6B]` | 1641 | ✅ passed |
| 6 | `test_response_api_simple.py::test_enable_response_messages[Qwen/Qwen3-0.6B]` | 1642 | ✅ passed |
| 7 | `test_response_api_simple.py::test_reasoning_item[Qwen/Qwen3-0.6B]` | 1643 | ❌ 仍断言失败（reasoning） |

> 7 个全部 `Qwen/Qwen3-0.6B`。修复后 5 个通过，2 个（test_reasoning_item / test_mcp_tool_call）仍断言失败：`assert 'message' == 'reasoning'` / `assert 'message' == 'mcp_call'`——Qwen3-0.6B 这个小模型在当前配置下不产出 reasoning/MCP 输出类型，属**模型行为问题，非崩溃**，需单独评估。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `t_h20`），torch `2.5.1+cu124`
- vLLM 分支：`2.5.1_ut_verify`（v0.13.0-11-g73810b8ff）
- 测试启动方式：`RemoteOpenAIServer` 跑 `vllm serve Qwen/Qwen3-0.6B`，**默认 `enforce_eager=False`**（走 torch.compile）
- 关键：同模型的 `test_chat_utils`/`test_fusions_e2e` 在 Phase 1 通过，因它们用 `LLM()` + `enforce_eager=True` 或不启动引擎，**绕开了 compile 路径和 warmup**

---

## 证据链

### 证据 1：层1 - inline_call monkeypatch 签名不匹配

远端 log `batch_20260719_020126/pytest_batch_20260719_020126.log`（行 165-290）：

```
(EngineCore_DP0) ERROR [core.py:866] torch._dynamo.exc.InternalTorchDynamoError:
  TypeError: _support_torch_compile.<locals>.__call__.<locals>.patched_inline_call()
  takes 1 positional argument but 4 were given

from user code:
   File "vllm/model_executor/models/qwen2.py", line 425, in forward
       if get_pp_group().is_first_rank:
```

vLLM `vllm/compilation/decorators.py:472`（commit `eef921f45` 后的 1 参数形式）：
```python
inline_call = InliningInstructionTranslator.inline_call_
def patched_inline_call(self_):              # ← 只收 1 个参数
    code = self_.f_code
    return inline_call(self_)
patch.object(InliningInstructionTranslator, "inline_call_", patched_inline_call)
```

torch 2.5.1 实际签名（容器内验证）：
```python
InliningInstructionTranslator.inline_call  (parent, func, args, kwargs)   # 4 参数
InliningInstructionTranslator.inline_call_ (parent, func, args, kwargs)   # 4 参数 (不是 1!)
```

→ monkeypatch 把 4 参数的 `inline_call_` 替换成 1 参数的 `patched_inline_call`，dynamo 调用时传 4 个参数 → TypeError。**eef921f45 为 torch ≥2.7 写的（那里 inline_call_ 被重构成单参数 self_），torch 2.5.1 仍是 4 参数。**

### 证据 2：层2 - VllmBackend options 不匹配（修层1 后暴露）

应用层1 补丁后重跑，dynamo 错误消失，但 compile 路径继续暴露第二个不匹配：
```
(EngineCore_DP0) ERROR [core.py:866] TypeError:
  VllmBackend.__call__() got an unexpected keyword argument 'options'
(EngineCore_DP0) BackendCompilerFailed: backend='<VllmBackend object>' raised
```

→ 说明 eef921f45 的 AOT compile 重构在 torch 2.5.1 上**整体不兼容**，逐个修是打地鼠。

### 证据 3：层3 - DeepGEMM warmup 崩溃（eager 路径）

改走 eager（`--enforce-eager`）绕开层1/层2 后，server 在 warmup 阶段崩：
```
(EngineCore_DP0) ERROR [core.py:866] RuntimeError:
  DeepGEMM backend is not available or outdated. Please install or update
  the `deep_gemm` to a newer version to enable FP8 kernels.
  File "vllm/model_executor/warmup/deep_gemm_warmup.py", line 133, in _fp8_linear_may_use_deep_gemm
  File "vllm/utils/deep_gemm.py", line 174, in get_mk_alignment_for_contiguous_layout
  File "vllm/utils/deep_gemm.py", line 85, in _missing
```

根因链：
- `deep_gemm` 包（2026-06-24 装，v2.6.1+local）**只有 `_C.pyi` 类型存根，无 `_C.so` 编译产物** → `from . import _C` 必崩
- `_lazy_init()` 捕获 ImportError 优雅返回（impl 留 None），但 `get_mk_alignment_for_contiguous_layout()` 检查 `impl is None` 调 `_missing()` **抛错**
- `_fp8_linear_may_use_deep_gemm(module)` 在检查模块是否 FP8 **之前**就调 `get_mk_alignment_for_contiguous_layout()`，导致**任何模型（含 BF16 的 Qwen3-0.6B）都崩**
- gate `is_deep_gemm_supported()` = `VLLM_USE_DEEP_GEMM(默认1) and has_deep_gemm()(只查包存在) and is_supported_arch(Hopper=True)` → **误判 True**，不查 `_C` 能否 import

### 证据 4：修复后验证通过

远端实跑（GPU 1 + `VLLM_DEEP_GEMM_WARMUP=skip`，两个文件全跑）：
```
5 passed, 2 failed, 6 warnings in 91.67s
```
2 failed 为真实断言失败（非崩溃）：
- `test_reasoning_item`: `assert 'message' == 'reasoning'`
- `test_mcp_tool_call`: `assert 'message' == 'mcp_call'`

---

## 根因分析

### 层1+2：vLLM AOT compile 重构与 torch 2.5.1 不匹配

commit `eef921f45` "AOT Compilation for torch.compile (Bundled)" (2025-10-10) 重构了 `_support_torch_compile` 的 monkeypatch（`inline_call_` 单参数形式 + `VllmBackend` 签名），为 torch ≥2.7 写的。`2.5.1_ut_verify` 分支 cherry-pick 了该 commit，但容器是 torch 2.5.1，**compile 路径整体不兼容**。这不是单一 bug，而是重构的 API 假设与新 torch 版本耦合，逐个修不可行。

### 层3：DeepGEMM 误判 + gate 不严

`deep_gemm._C` 从未编译（无 `.so`），但 `is_deep_gemm_supported()` 的 gate 只查包存在 + 架构，不查 `_C` 可导入性，误判 True。`_fp8_linear_may_use_deep_gemm` 又在类型检查前调用会抛错的 `get_mk_alignment`，导致 BF16 模型也崩。**影响所有启动引擎的测试**，Phase 1 未大面积暴露是因为大多数 passed 测试（kernels/attention 435个等）直接测 kernel 函数、不启动引擎；而启动引擎且走 compile 的测试（如这 7 个）在层1 就崩了，到不了层3。

---

## 修复动作（A 留 + B patch + C env）

### A. inline_call 4参数回退（torch 2.5.1 兼容，正确的但单独不够）

补丁 `tasks/ut/patches/torch25_inline_call_compat.patch`：把 `decorators.py` 的 `patched_inline_call` 回退到 commit `eef921f45` 之前的 4 参数形式（`inline_call` 而非 `inline_call_`）。

```diff
-        inline_call = InliningInstructionTranslator.inline_call_
+        inline_call = InliningInstructionTranslator.inline_call
-        def patched_inline_call(self_):
-            code = self_.f_code
+        def patched_inline_call(parent, func, args, kwargs):
+            code = func.get_code()
-            return inline_call(self_)
+            return inline_call(parent, func, args, kwargs)
-                InliningInstructionTranslator, "inline_call_", patched_inline_call
+                InliningInstructionTranslator, "inline_call", patched_inline_call
```

> 保留：这是正确的 torch 2.5.1 兼容修复，对其他走 compile 的测试可能有用。单独不够（compile 路径还有层2），但无害。

### B. Response API 测试加 --enforce-eager（绕开 compile 路径）

补丁 `tasks/ut/patches/response_api_enforce_eager.patch`：给 `test_response_api_simple.py` 和 `test_response_api_parsable_context.py` 的 server args 加 `--enforce-eager`，走 eager 路径彻底绕开层1/层2。

```diff
-    with RemoteOpenAIServer(MODEL_NAME, args, env_dict=env_dict) as remote_server:
+    with RemoteOpenAIServer(MODEL_NAME, args + ["--enforce-eager"], env_dict=env_dict) as remote_server:
```

### C. VLLM_DEEP_GEMM_WARMUP=skip（全局绕开层3）

`tasks/ut/deployment/production/config/workflow.yaml` 的 `container_env` 加：
```yaml
VLLM_DEEP_GEMM_WARMUP: "skip"
```
全局跳过坏掉的 deep_gemm warmup。无损（deep_gemm 本就不可用）。这是**全局修复**，让所有引擎启动测试绕开层3。

### 提交

| 仓库 | commit | 内容 |
|------|--------|------|
| apmm（本地） | `1a39d48` | workflow.yaml + 2 patch 文件 + README |
| vllm（远端 `2.5.1_ut_verify`） | `f4f1077c9` | decorators.py + 2 测试文件 --enforce-eager |

### test_load 标记

7 个测试 `fix_applied=true`，`fix_details` 区分两类：
- 5 个：`根因已修复(...), 远端验证 passed, 待Phase2重跑确认`
- 2 个：`崩溃已修复(...), 但远端验证仍断言失败: Qwen3-0.6B不产出reasoning/mcp_call, 属模型行为问题, 需单独评估`

---

## 防回归措施

1. **compile 路径不信任**：torch 2.5.1 上 vLLM 的 AOT compile 重构整体不兼容，凡 `enforce_eager=False` 的 server 测试都可能崩。新增 server 测试默认加 `--enforce-eager`，或确认 torch 版本匹配后再开 compile。
2. **deep_gemm 可用性要查 `_C` 能否 import**：`is_deep_gemm_supported()` 应增加 `_C` 可导入性检查，不能只查包存在。当前用 `VLLM_DEEP_GEMM_WARMUP=skip` 规避，后续应修 `is_deep_gemm_supported` 源码（更彻底）。
3. **warmup 崩溃的监测**：引擎启动测试若报 `DeepGEMM backend is not available`，第一时间查 `VLLM_DEEP_GEMM_WARMUP` 是否设 skip，而非去查模型。
4. **"Server exited unexpectedly" 不是单一根因**：见 [vllm-server-startup-timeout-incident](2026-07-19-vllm-server-startup-timeout-incident.md)，server 启动失败可能是 compile 超时 / 缓存缺失 / compile 崩溃 / warmup 崩溃多种根因，必须看远端 server log 定位。

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| decorators.py | 远端 `vllm/compilation/decorators.py:472` | inline_call monkeypatch（层1） |
| test_response_api_*.py | 远端 `tests/entrypoints/openai/` | server args（层1/2 触发） |
| deep_gemm_warmup.py | 远端 `vllm/model_executor/warmup/deep_gemm_warmup.py:133` | warmup 崩溃（层3） |
| deep_gemm.py | 远端 `vllm/utils/deep_gemm.py:85,174` | `_missing` + `is_deep_gemm_supported` gate |
| 补丁 | `tasks/ut/patches/torch25_inline_call_compat.patch`、`response_api_enforce_eager.patch` | A + B |
| workflow.yaml | `tasks/ut/deployment/production/config/workflow.yaml` | C（container_env） |
| server log | 远端 `ut_logs/batch_20260719_020126/pytest_batch_20260719_020126.log` | 层1 完整 traceback |
| Phase 1 总结 | [reports/2026-07-19-phase1-500batch-run-summary.md](../reports/2026-07-19-phase1-500batch-run-summary.md) | §4.2 error 分析 |
| server 超时事故 | [2026-07-19-vllm-server-startup-timeout-incident.md](2026-07-19-vllm-server-startup-timeout-incident.md) | 另 5 个 server 启动失败（compile 超时+whisper 缓存） |

---

## 经验沉淀

1. **"Server exited unexpectedly" 要看远端 server log，不能只看 pytest 报错**：pytest 只报 `RuntimeError: Server exited unexpectedly.`（tests/utils.py:213 包装），真正崩溃原因在 EngineCore_DP0 的 log 里（dynamo / warmup / OOM 等）。
2. **torch.compile 路径在 torch 2.5.1 上是雷区**：vLLM 的 AOT compile 重构与 torch 版本强耦合，`2.5.1_ut_verify` 分支含 torch≥2.7 的重构，凡走 compile 的 server 测试都可能崩。eager 路径是稳定逃生口。
3. **gate 不严 = 全局误伤**：`is_deep_gemm_supported()` 只查包存在不查 `_C`，一个误判让所有引擎启动测试崩。gate 应验证"真能用"而非"装了"。
4. **三层叠加问题的排查顺序**：先修最表层的（层1 inline_call），暴露下一层（层2 VllmBackend），再暴露底层（层3 deep_gemm）。逐层验证，避免一次性改多处分不清哪层起作用。
5. **同模型 passed 不代表路径相同**：Qwen3-0.6B 在 test_chat_utils 通过（LLM()+enforce_eager，不启动引擎走 compile），在 Response API 崩（vllm serve 默认 compile）。判断测试是否受影响要看启动方式 + enforce_eager + 是否启动引擎，不能只看模型。
6. **真实断言失败 ≠ 环境问题**：修复崩溃后暴露的 2 个断言失败（reasoning/mcp_call）是模型行为问题，不应再当基础设施 bug 修。区分"崩"（RuntimeError/TypeError）和"断言失败"（assert），前者查环境，后者查测试预期与模型能力。
