# flashmla FP8 kernel 在 H20 上输出错误事故（C++ 扩展非 triton）

**日期**: 2026-07-19
**严重等级**: P2（48 个 failed 测试的根因，平台兼容问题，非代码 bug 也非环境配置错误）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），48 个 `tests/kernels/attention/test_flashmla.py` FP8 参数化用例恒定失败
**修复状态**: 📐 待排查（根因定位到 C++ kernel FP8 路径，具体原因待 H20/H100 对比确认）

---

## 事故概述

Phase 1 的 91 个 failed 测试中，48 个来自 `tests/kernels/attention/test_flashmla.py`，全部参数化为 `torch_dtype2`（即 `torch.float8_e4m3fn`）。失败断言 `assert cos_diff < 1e-4`，实际 cos_diff 0.27~0.98 或 nan。

关键结论：**flashmla 是 C++/CUDA 编译扩展（`vllm._flashmla_extension_C`），不是 triton kernel**，与同期的 triton 3.5.0 版本冲突事故**无关**。bf16/fp16 路径（`_flashmla_C.fwd_kvcache_mla`）49 个全 passed，只有 FP8 路径（`_flashmla_extension_C.fwd_kvcache_mla_fp8`）输出错误。

错误不是 import/编译失败，而是 kernel **运行后部分位置输出错误**（出现大值/nan），属平台兼容问题（P-平台兼容）。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `t_h20`）
- GPU：NVIDIA H20-3e × 8（Hopper 架构，compute capability 9.0 / sm_90a）
- 测试：`tests/kernels/attention/test_flashmla.py::test_flash_mla[torch_dtype2-...]`
- `torch_dtype2` = `torch.float8_e4m3fn`（FP8 E4M3）
- 参数化固定模式：`block_size=64, dv=512, d=576, h_kv=1, causal=True`，变化 `varlen{False,True} × h_q{16,32,64,128} × mean_sk{4096,8192,16384} × s_q{1,2}`

---

## 证据链

### 证据 1：48 个失败全是 FP8，bf16/fp16 全过

`test_flash_mla` 参数化（源码）：
```python
@pytest.mark.parametrize("torch_dtype", [torch.bfloat16, torch.float16, torch.float8_e4m3fn])
#                                                    dtype0          dtype1         dtype2
```

| dtype | 状态 | 数量 |
|-------|------|------|
| torch.bfloat16 (dtype0) | passed | 部分 |
| torch.float16 (dtype1) | passed | 部分 |
| **torch.float8_e4m3fn (dtype2)** | **failed** | **48** |

同文件总计：passed=49, failed=48, ignored=31。**失败 100% 集中在 FP8**。

### 证据 2：flashmla 是 C++ 扩展，非 triton

`vllm/attention/ops/flashmla.py`：
```python
import vllm._flashmla_C            # bf16/fp16 路径
import vllm._flashmla_extension_C  # FP8 路径

if use_fp8:  # descale_q is not None
    out, lse = torch.ops._flashmla_extension_C.fwd_kvcache_mla_fp8(...)
else:
    out, lse = torch.ops._flashmla_C.fwd_kvcache_mla(...)
```

- `_flashmla_C.fwd_kvcache_mla`（bf16/fp16）-> 49 passed
- `_flashmla_extension_C.fwd_kvcache_mla_fp8`（FP8）-> 48 failed

**与 triton 3.5.0 版本冲突无关**（那个事故影响 test_fusion_attn 的 inductor 编译，本事故是 C++ kernel 运行时）。

### 证据 3：cos_diff 分布显示结果完全错误，非精度损失

断言逻辑（`cal_diff`）：
```python
cos_diff = 1 - 2 * (x * y).sum() / max((x*x + y*y).sum(), 1e-12)
if use_fp8:
    assert cos_diff < 1e-4    # FP8 容差
```

48 个失败的 cos_diff 分布：

| cos_diff | 数量 | 含义 |
|----------|------|------|
| nan | 15 | 输出含 nan |
| 0.5 ~ 1.0 | 27 | 几乎正交，结果完全错 |
| 0.1 ~ 0.5 | 6 | 严重偏差 |
| < 0.01 | 0 | 无（对比：bf16/fp16 均 < 1e-5 通过） |

数值范围 0.2733 ~ 0.9835。**这不是 FP8 精度损失（那种应在 1e-3 量级），是 kernel 输出根本性错误**。

### 证据 4：traceback 显示输出部分位置错误

测试 1.5s 完成（kernel 确实执行，非 import 失败）。traceback 的 x（flashmla FP8 输出）vs y（参考 sdpa）：

```
x = [[[-0.0325, -0.0303, -0.1177, ...,  0.0056,  0.0544,  0.0320],   # 前部: 正确(与y接近)
      ...,
      [..., 1.1016, ..., 2.9102, 1.9453, -1.0234]]]                    # 后部: 大值(应~0.05)
y = [[[-0.0329, -0.0304, -0.1181, ...,  0.0051,  0.0547,  0.0320],   # 前部: 一致
      ...,
      [..., 0.0561, ..., -0.0033, -0.0184, -0.0028]]]                  # 后部: 小值
```

**flashmla FP8 在大部分位置正确，部分位置出现 1.9/1.1 等错误大值**，拉高 cos_diff 到 0.98。

### 证据 5：硬件检查通过（H20 是 Hopper，flashmla 支持）

```python
def is_flashmla_dense_supported():
    if current_platform.get_device_capability()[0] != 9:
        return False, "FlashMLA Dense is only supported on Hopper devices."
    return True, None
# H20 = Hopper cc 9.0 -> 支持，测试未被 skip，确实运行
```

### 证据 6：FP8 kernel 源码明确针对 sm90a

`cmake/external_projects/flashmla.cmake` 第 35 行注释 `# sm90a`，第 46 行 `cuda_archs_loose_intersection(FLASH_MLA_ARCHS ...)`。FP8 kernel 文件名直接是 `flash_fwd_mla_fp8_sm90.cu`，针对 Hopper 编写。H20 是 sm_90a，编译包含此 kernel。

---

## 根因分析

### 直接原因

`_flashmla_extension_C.fwd_kvcache_mla_fp8`（FP8 前向 kernel）在 H20-3e 上运行时，部分位置输出错误大值/nan，导致与参考实现 cos_diff 远超 1e-4 容差。

### 根本原因（待确认）：H20-3e 与 H100 的 FP8 硬件行为差异

- H100（sm_90a）支持 FP8 E4M3（已确认）
- H20-3e（sm_90a）同为 Hopper 架构，理论上也支持 E4M3
- **但 FP8 kernel 在 H20 上输出错误**，而相同代码在 H100 上预期正常（待验证）

可能的具体原因：
1. **H20-3e 的 FP8 tensor core 规格/吞吐与 H100 不同**，kernel 的 warp/CTA 调度或分块假设在 H20 上不成立
2. **kernel 用了 H100 特有而 H20-3e 缺失的 FP8 硬件特性**（如某些 TMA / wgmma FP8 指令变体，或 FP8 加速单元降配）
3. H20-3e 可能是 H20 的降配型号（"3e"），FP8 单元规格与 H100/H20 标准版不同

### 排除项

- ❌ triton 版本：flashmla 是 C++ 扩展非 triton kernel
- ❌ 模型/权重：测试用 `torch.randn` 随机数据，不依赖外部模型
- ❌ import/编译失败：kernel 确实运行了（1.5s），输出是错误值而非异常
- ❌ descale 逻辑：descale 均为 1.0，且参考实现用同样 descale

---

## 建议排查方法

### 1. H100 对比验证（确认平台差异，最高优先级）

在 H100（sm_90a）环境跑同一批 FP8 测试，若全部 pass 则坐实 H20 平台兼容问题：
```bash
# 在 H100 容器内
pytest -v tests/kernels/attention/test_flashmla.py -k "torch_dtype2"
```
若无 H100 环境，查 vllm CI / 上游对该测试的 pass 记录。

### 2. 查 vllm 上游 issue

搜 vllm-project/vllm 的 issues/PR：`H20 flashmla fp8`、`flashmla fp8 incorrect output`、`_flashmla_extension_C`。确认是否已知 H20 兼容问题，是否有修复 PR。

### 3. 读 FP8 kernel 源码核心计算

源码位置：
```
/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src/csrc/extension/sm90/dense_fp8/
├── flash_fwd_mla_fp8_sm90.cu   ← FP8 前向 kernel 核心
├── fp8_transpose_v.h           ← FP8 V 转置
├── flash_fwd_mla_kernel.h
├── softmax.h
└── ...
```
重点看：
- FP8 矩阵乘用了哪些 PTX 指令（`wgmma.mma_async.sync.aligned.m64n128k32.f8f6f4` 等）
- 是否用了 H100 独有的 FP8 tensor core 指令变体
- softmax/lse 计算在 FP8 路径的数值处理

### 4. 对比 H20-3e 与 H100 的 FP8 硬件规格

查 NVIDIA 官方 spec：H20-3e 的 FP8 tensor core TFLOPS、是否完整支持 E4M3/E5M2、TMA/wgmma FP8 指令支持情况。确认是否降配导致某些 FP8 指令行为不同。

### 5. 单步调试（如需深挖）

在容器内用 `cuda-gdb` 或加打印跑单个 FP8 测试，定位错误大值出现在 kernel 的哪个计算阶段（QK^T / softmax / PV）。

### 6. 短期止血

在 `skills/ut/ut_common/filter_rules.yaml` 排除 flashmla 的 FP8 参数化（`torch_dtype=torch.float8_e4m3fn`），将这 48 个标记 ignored 而非 failed，避免污染通过率，待平台问题确认后再决定是否重跑。

---

## 影响与待办

### 对 Phase 1 数据的影响

- 48 个 failed 实为 `platform_compat`（H20 FP8 兼容），非 `assertion`
- Phase 1 真实通过率修正：排除这 48 个 + 19 个 triton 后，passed/(passed+真 failed) 显著上升

### 与其他失败的关系

| 类别 | 数量 | 根因 | 与本事故关系 |
|------|------|------|-------------|
| triton 版本冲突 | 19 | triton 3.5.0 vs torch 2.5.1 | **独立**（test_fusion_attn，inductor 编译） |
| **flashmla FP8** | **48** | **C++ kernel FP8 在 H20 bug** | **本事故** |
| HF 加载失败 | 16 | 网络/缓存 | 独立 |
| 其他 | 8 | server/chat_utils 等 | 独立 |

**修复 triton 版本不会修复 flashmla FP8**，两者是独立问题。

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 失败测试 | `tests/kernels/attention/test_flashmla.py` | 48 个 FP8 参数化用例 |
| Python 接口 | `vllm/attention/ops/flashmla.py` | `flash_mla_with_kvcache`，FP8 分支调 `_flashmla_extension_C` |
| **FP8 kernel 源码** | `.deps/FlashMLA-src/csrc/extension/sm90/dense_fp8/flash_fwd_mla_fp8_sm90.cu` | **根因所在** |
| FP8 V 转置 | `.deps/FlashMLA-src/csrc/extension/sm90/dense_fp8/fp8_transpose_v.h` | FP8 V 处理 |
| 构建配置 | `cmake/external_projects/flashmla.cmake` | FLASH_MLA_ARCHS=sm90a，第 67-69 行 FP8 源文件 |
| 编译产物 | `vllm/_flashmla_extension_C.abi3.so` | FP8 扩展 .so |
| test_load | `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | 48 个 failed 记录 |
| 远端日志 | `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260719_095645/pytest_batch_20260719_095645.log` | 完整 traceback（含 x/y 张量值） |
| 过滤规则 | `skills/ut/ut_common/filter_rules.yaml` | 短期止血落点 |
| 关联事故 | `incidents/2026-07-19-triton-torch-version-conflict-incident.md` | triton 版本冲突（独立事故） |
| Phase 1 总结 | `reports/2026-07-19-phase1-500batch-run-summary.md` | §4.1 failed 分析 |

---

## 经验沉淀

1. **error_message 精简版会掩盖真相**：test_load 只存 `assert 0.98 < 0.0001` 一行，看不出是 FP8 路径；完整 traceback（含 x/y 张量值、captured stdout 的 `torch_dtype=`）才暴露 FP8。后续失败分析应优先拉完整日志。
2. **参数化 dtype 编号要溯源**：`torch_dtype2` 不直观，必须回源码 `@parametrize` 顺序确认是 `float8_e4m3fn`。分析时第一参数分布（48 个全是 dtype2）是关键线索。
3. **"同文件部分 pass 部分 fail" 是定位利器**：49 passed (bf16/fp16) vs 48 failed (fp8) 直接锁定 FP8 路径，排除了 kernel 加载/硬件不支持等全局问题。
4. **C++ 扩展与 triton kernel 要区分**：flashmla 走 `_flashmla_C` / `_flashmla_extension_C`（C++ CUDA），不受 triton 版本影响。排查前先确认 kernel 类型，避免错误归因到 triton。
5. **平台兼容问题（P 类）的特征**：kernel 能运行、部分位置对部分位置错、同架构不同型号表现不同 -> 指向硬件指令行为差异，而非代码逻辑或环境配置。
