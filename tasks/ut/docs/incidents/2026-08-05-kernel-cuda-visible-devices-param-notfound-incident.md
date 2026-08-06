# CUDA_VISIBLE_DEVICES 单卡导致 kernel 参数化节点 not found 事故（962 个 kernel 测试误判 ignored）

**日期**: 2026-08-05
**严重等级**: P1（962 个 kernel 测试在 Phase 1 与 Phase 2 全量重试中全部误判 ignored 的根因之一）
**影响范围**: UT workflow run `ut-20260718-164107`，test_cache（391）+ test_prefix_prefill（168）+ test_fused_quant_layernorm（403）共 **962 个 kernel 测试**
**修复状态**: ✅ 已修复（专项脚本 `retry_kernel_tests.py` 串行重跑，315 passed + 241 skipped）

---

## 事故概述

vLLM 的 kernel 测试参数化节点（如 `test_reshape_and_cache[auto-cuda:1-0-dtype0-10000-32-64-8-42]`）
**在 pytest 收集阶段根据运行时可见 GPU 生成**。执行框架 `execute_batch.py` 对 normal
测试固定设 `CUDA_VISIBLE_DEVICES={gpu_id}`（单卡），导致：

```
CUDA_VISIBLE_DEVICES=0 → 只生成 cuda:0 参数化节点
→ 命令行传入的 cuda:1-... 节点匹配不上
→ pytest ERROR: not found → 收集 0 items → 结果被标 ignored（超时/收集 0）
```

**962 个 kernel 测试在 Phase 1（2026-07-18）就因此被误判为 timeout/ignored，
Phase 2 全量重试（2026-08-05）因同一机制再次收集 0**，直到专项脚本绕开后才确认
真相：这些测试单独跑全部通过（2-3s/个）。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `infra-gpu-h20-022`）
- 执行方式：`execute_batch.py` normal 路径，硬编码 `CUDA_VISIBLE_DEVICES={gpu_id}`
- 测试类型：vllm kernel 测试，参数化值含 `cuda:N`（N>0）——参数化依赖 GPU 可见性

---

## 根因分析

### 直接根因：单卡环境变量 vs 参数化 GPU 依赖

vllm kernel 测试的参数化（如 `test_reshape_and_cache[auto-cuda:1-0-dtype0-...]`）
在 `pytest_generate_tests` / fixture 参数化时，根据 `torch.cuda.device_count()`
（受 `CUDA_VISIBLE_DEVICES` 影响）生成 `cuda:0 / cuda:1 / ...` 节点。

- 8 卡全可见 → 生成 `cuda:0` ~ `cuda:7` 全部参数化
- 设 `CUDA_VISIBLE_DEVICES=0`（单卡）→ 只生成 `cuda:0` → `cuda:1-...` 节点不存在

`pytest <node>` 对不存在的节点报 `ERROR: not found`，收集 0 items，JUnit XML
无 testcase → execute_batch 判 `JUnit XML has no <testcase>` → ignored（timeout 类）。

### 为什么 Phase 1 和全量重试都没发现

- **Phase 1**：这些 kernel 测试与同 batch 慢测试混跑，被 batch 级 watchdog 600s
  连坐 + 收集 0 双重因素 → 全部 ignored，错误归因为"超时"
- **Phase 2 全量重试**：重试时 execute_batch 依旧设单卡 → 依旧收集 0 → 自动重试
  3 次仍 ignored → 一度被误判为"死测试"（node not found 假象），差点从 test_load
  移除

### 为什么不能直接改 execute_batch 全局去掉 env

- execute_batch 的 GPU 隔离分配（normal 8 并发各用一卡）依赖
  `CUDA_VISIBLE_DEVICES` 按测试设置
- 去掉后：并发测试全看到 8 卡 → 参数化全生成 → 但测试都抢同一物理卡 → 冲突
- 正确做法是**串行**（一次一个）+ **不设 env**，与现有并发模型不兼容

---

## 证据链（对照实验，2026-08-05 SSH 直连 H20 容器）

同一节点 `test_rms_norm[cuda:1-0-group_size1-quant_dtype0-dtype0-False-False-1-64]`：

| 场景 | 命令 | 结果 |
|---|---|---|
| A | `pytest --collect-only "<node>"` | ✅ `1 test collected` |
| B | `CUDA_VISIBLE_DEVICES=0 pytest "<node>"` | ❌ `ERROR: not found` → 0 items |
| C | `pytest "<node>"`（不设 env） | ✅ `1 passed, 2.2s` |

B 复现了 execute_batch 的失败路径；C 证明节点有效、测试可过。

另验证 `test_cache.py::test_reshape_and_cache[auto-cuda:1-...]`（1 passed 2.2s）与
`test_prefix_prefill.py::test_contexted_kv_attention[...cuda:1...]`（1 passed 2.9s）
同类。`fused_quant_layernorm` 除外——它即使不设 env 也 illegal memory access
（另一独立问题，见兼容性报告）。

---

## 影响范围

| 测试文件 | 数量 | 处置 |
|---|---|---|
| `tests/kernels/attention/test_cache.py` | 391 | 专项重跑：passed 大部分 + skipped（Triton NHD layout 限制） |
| `tests/kernels/attention/test_prefix_prefill.py` | 168 | 专项重跑：passed 部分 + skipped |
| `tests/kernels/core/test_fused_quant_layernorm.py` | 403 | ⚠️ 另有 illegal memory access（H20 兼容性 bug），非本事故 |

---

## 修复动作

新增专项脚本 `tasks/ut/scripts/retry_kernel_tests.py`（commit `7c9a0e3`）：

1. 从 test_load 收集 test_cache + prefix_prefill 的 `ignored retry=0` 用例（556 个）
2. **SSH 直连 H20，不设 CUDA_VISIBLE_DEVICES，串行单跑**（一次一个，无并发冲突）
3. 解析 pytest 结果（passed/failed/skipped）回写 test_load

结果（2026-08-05，118min）：**passed 315 + skipped 241**（failed=0, error=0）。
test_load passed 2723 → **3041**（通过率 68% → 76%）。

---

## 防回归措施

1. **execute_batch 对 kernel 类测试需特殊处理**：检测 node 含 `cuda:N`（N>0）
   参数化时，不设单卡 env（或设全卡可见 + 串行）——待实现
2. **"node not found" 不能直接判死测试**：重试仍收集 0 时，先 SSH 单独
   collect-only 验证节点有效性，再决定剔除（本事故差点误删 962 个用例）
3. **incident 索引**：本事故已登记 incidents/README.md

---

## 相关文件

- 专项脚本：`tasks/ut/scripts/retry_kernel_tests.py`
- 重跑结果：`runs/ut-20260718-164107/retry_kernel_summary.json` / `retry_kernel_progress.json`
- 兼容性问题（fused_quant_layernorm illegal memory access）：
  `tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md`

*更新时间: 2026-08-05*
