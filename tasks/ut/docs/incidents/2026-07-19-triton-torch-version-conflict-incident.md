# triton 3.5.0 与 torch 2.5.1 版本冲突事故（vllm vs inductor 依赖不兼容）

**日期**: 2026-07-19
**严重等级**: P2（19 个 failed 测试的根因，且无法用简单升降级修复，需协调 vllm/torch 版本）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），19 个 `tests/compile/test_fusion_attn.py` 测试恒定失败
**修复状态**: 📐 待评估（根因已坐实，修复方向需权衡，见 §修复方案）

---

## 事故概述

Phase 1 的 91 个 failed 测试中，19 个来自 `tests/compile/test_fusion_attn.py`，全部参数化为 `AttentionBackendEnum.TRITON_ATTN`。19 个错误信息**一字不差**，被分类为 `error_type=assertion`，实际是 **torch inductor 与 triton 版本不兼容**导致的 `ImportError`。

本地 test_load / batch_results 只存了 480 字符的**外层**精简错误（`BackendCompilerFailed: ... Cannot find a working triton installation ... too old`），看起来像"triton 没装"。远端容器实测拿到**内层**真实错误：`ImportError: cannot import name 'triton_key' from 'triton.compiler.compiler'` -- triton 3.5.0 删除了 torch 2.5.1 inductor 依赖的 `triton_key` 符号。

关键矛盾：**vllm 当前版本需要 triton 3.5.0，torch 2.5.1 需要 triton == 3.1.0**，同一容器无法同时满足，是依赖冲突而非"装错版本"。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `t_h20`）
- torch 2.5.1+cu124，triton 3.5.0，Python 3.12
- 测试：`tests/compile/test_fusion_attn.py::test_attention_quant_pattern[AttentionBackendEnum.TRITON_ATTN-...]`
- 测试体走 `torch.compile(backend='inductor')` 编译路径

---

## 证据链（远端容器实测）

诊断脚本 `runs/ut-20260718-164107/diag_triton.py`，通过 `agent.py run` + base64 在容器内执行（避开不稳定的 SFTP）。

### 证据 1：torch 声明的 triton 依赖

```
torch requires: triton (==3.1.0) ; platform_system == "Linux" and platform_machine == "x86_64" and python_version < "3.13"
```

torch 2.5.1 的 METADATA 明确要求 `triton == 3.1.0`。容器实际装的 3.5.0 不在约束内。

### 证据 2：实际 ImportError（内层真实错误）

```
torch._dynamo.exc.BackendCompilerFailed: backend='inductor' raised:
ImportError: cannot import name 'triton_key' from 'triton.compiler.compiler'
  (/usr/local/lib/python3.12/dist-packages/triton/compiler/compiler.py)
```

torch 2.5.1 的 inductor 代码执行 `from triton.compiler.compiler import triton_key`，triton 3.5.0 已删除/改名 `triton_key`，import 失败。

### 证据 3：调用栈（纯 torch，无 vllm 帧）

```
torch.compile(backend='inductor')
  -> torch/_dynamo/output_graph.py: compile_and_call_fx_graph
    -> call_user_compiler -> _call_user_compiler
      -> raise BackendCompilerFailed(self.compiler_fn, e)
```

异常在 **torch._dynamo / torch._inductor** 内部抛出，调用栈无 vllm 帧。vllm 是编译请求的发起方，错误在 torch 编译后端产生。

### 证据 4：inductor 模块 import 本身成功

```
=== inductor import triton ===
inductor triton import: OK
```

`from torch._inductor.codegen import triton` 能 import -- 只有**真正触发编译**时才走到 `triton_key` 那行失败。这解释了为什么测试在 collection 阶段不挂、跑到编译才挂（duration ~3.7s）。

### 证据 5：smoke test 复现

`torch.compile(lambda x: x+1, backend='inductor')` 在容器内稳定复现同一 `ImportError`，与 19 个测试的错误一致。

---

## 根因分析

### 直接原因

torch 2.5.1 的 inductor 代码依赖 `triton.compiler.compiler.triton_key`，该符号在 triton 3.5.0 中不存在（triton 3.1.0 -> 3.5.0 之间有 breaking change，`triton_key` 被移除/改名）。触发编译时 import 失败，包装成 `BackendCompilerFailed`。

### 根本原因：依赖冲突

| 组件 | 要求的 triton 版本 |
|------|-------------------|
| torch 2.5.1+cu124（METADATA 声明） | `==3.1.0` |
| vllm 当前版本（实际运行需要） | `3.5.0` |

同一容器无法同时满足。这不是"装错版本"，是 **vllm 与 torch 2.5.1 在 triton 版本上存在不可调和的冲突**。

### 为什么之前误判为"assertion / 网络错误"

- 本地 test_load 只存 `error_message` 外层 480 字符精简版，文案 "Cannot find a working triton installation ... too old" 像环境缺失
- Phase 1 运行总结报告 §4.1 把 91 个 failed 笼统归为"HuggingFace 网络错误"（抽样多数是 HF），未区分这 19 个 triton 错误
- `error_type` 被分类为 `assertion`，实际应为 `dependency`

---

## 修复方案（权衡）

### 方案 A：降 triton 到 3.1.0 ❌ 不可行

`pip install triton==3.1.0` 满足 torch 2.5.1，但 **vllm 当前版本需要 triton 3.5.0**，降级会导致 vllm 调用 triton 出问题。拆东墙补西墙。

### 方案 B：升 torch 到 2.7+ 配 triton 3.5.0 ❓ 待验证

torch 2.7.x 配 triton 3.3.x，2.8 配 3.4/3.5。但：
- 容器名是 `v0.13.0_torch2.5.1_compile`，升级 torch 改动大
- 需验证 vllm v0.13.0 是否兼容 torch 2.7+
- 可能引入新的兼容性问题

### 方案 C：新建 torch 2.5.1 + triton 3.1.0 专用容器 🟡 隔离

保留当前 `v0.13.0_torch2.5.1_compile`（triton 3.5.0，给 vllm 用），另建一个 `..._torch2.5.1_compile_triton31` 容器（triton 3.1.0）专跑 inductor 编译类测试。测试路由按 backend 类型分容器。

### 方案 D：filter_rules 排除 TRITON_ATTN 参数化 🟡 治标

在 `skills/ut/ut_common/filter_rules.yaml` 排除 `AttentionBackendEnum.TRITON_ATTN` 参数化，这 19 个测试在当前环境永远跑不了，标记 ignored 而非 failed，避免污染通过率。

### 方案 E：vllm 侧适配 ❓ 待评估

确认 vllm 对 triton 的真实下限。若 vllm 能在 triton 3.1.0 下运行（即使声明 3.5.0），则方案 A 可行。需查 vllm 的 triton 使用点是否依赖 3.5.0 新 API。

**当前推荐**：方案 D（短期止血，标记 ignored）+ 方案 C 或 E（长期解决）。最终方案需结合 vllm 团队对 triton 版本的要求确认。

---

## 影响与待办

### 对 Phase 1 数据的影响

- 19 个 failed 实为 `dependency`（环境冲突），非 `assertion`，应重分类
- Phase 1 真实通过率修正：排除这 19 个后，passed/(passed+真 failed) 会上升

### 对待办项文档的影响

[`reports/2026-07-19-phase1-pending-todos.md`](../reports/2026-07-19-phase1-pending-todos.md) 中：
- **P1-3（failed 重新分类）**：这 19 个重分类为 `dependency`（非 `network`/`download_error`），根因是版本冲突
- **P1-4（error 排查）**：与 openai entrypoints 的 12 个 error 无关，独立项
- 新增待办：**triton 版本冲突的容器策略**（方案 C/E 评估）

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 诊断脚本 | `runs/ut-20260718-164107/diag_triton.py` | 容器内实测脚本（版本/import/compile smoke） |
| 失败测试 | `tests/compile/test_fusion_attn.py` | 19 个 TRITON_ATTN 参数化用例 |
| test_load | `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | 19 个 failed 记录（error_message 仅外层 480 字符） |
| batch_results | `runs/ut-20260718-164107/batches/batch_20260719_000057/batch_results.json` | 含远端 raw_log 路径 |
| 远端 raw_log | `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260719_000057/pytest_batch_20260719_000057.log` | 808KB 完整日志（bastion 可达时可拉取） |
| 过滤规则 | `skills/ut/ut_common/filter_rules.yaml` | 方案 D 落点 |
| Phase 1 总结 | `reports/2026-07-19-phase1-500batch-run-summary.md` | §4.1 误判来源 |
| 待办项 | `reports/2026-07-19-phase1-pending-todos.md` | P1-3/P1-4 受影响 |

---

## 诊断过程备忘（给后续排查者）

1. **本地数据先看，但别全信**：test_load 的 `error_message` 是外层精简版（480 字符），真实原因在内层异常。batch_results 也没有完整 traceback。
2. **远端实测拿铁证**：用 `python tools/agent.py -p t_h20 run --timeout 180 "sudo docker exec <container> python3 -c \"...\""` 在容器内跑诊断。脚本用 base64 编码塞进 `python3 -c "exec(base64.b64decode('...'))"`，**避开 SFTP**（SFTP 不稳定，会搞坏 daemon 的 SSH 通道）。
3. **bastion daemon 维护**：`agent.py ping` 报 OK 但 `run` 报 `Socket is closed` = SSH 会话挂了，需 `stop` + `serve`（需 OTP）重启。SFTP 失败是常见诱因。
4. **METADATA 是版本约束的权威来源**：`import importlib.metadata as md; md.requires("torch")` 直接给出 torch 声明的 triton 版本约束，比猜版本对应表可靠。
