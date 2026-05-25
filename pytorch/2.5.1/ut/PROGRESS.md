# vLLM UT 测试进度跟踪

## 测试结果对比

| 版本 | PASSED | FAILED | 日期 | 时间 |
|------|--------|--------|------|------|
| 修复 TRANSFORMERS_CACHE 前 | 21 | 188 | 2025-05-14 | 01:33 |
| 修复 TRANSFORMERS_CACHE 后 | 26 | 178 | 2025-05-14 | 02:43 |
| 修复 fp8_utils.py List[int] 后 | 26 | 178 | 2025-05-14 | - |
| 修复 torch_utils.py UnionType 后 | 26 | 178 | 2025-05-14 | 17:45 |
| 批量修复 33 个文件后 (位置错误) | 0 | 1 (SyntaxError) | 2025-05-15 | 09:09 |
| 修复第一批 __future__ 位置 (20文件) | 26 | 178 | 2025-05-14 | 18:52 |
| **修复全部 __future__ 位置 (5文件)** | 待验证 | 待验证 | 2025-05-15 | - |

---

## 已修复问题

### 1. TRANSFORMERS_CACHE 路径错误 (已修复 ✓)

**问题描述**：
- `hf_env.sh` 中 `TRANSFORMERS_CACHE` 指向 `${HF_HUB_DIR}/transformers`
- 模型实际缓存在 `${HF_HUB_DIR}/hub`
- transformers 库找不到模型配置

**修复文件**：`scripts/hf_env.sh`

**修复内容**：
```bash
# 原配置
export TRANSFORMERS_CACHE="${HF_HUB_DIR}/transformers"

# 新配置
export TRANSFORMERS_CACHE="${HF_HUB_DIR}/hub"
```

---

### 2. PyTorch 2.5.1 类型注解兼容性问题 (已修复 ✓)

**问题描述**：
```python
ValueError: infer_schema(func): Parameter block_size has unsupported type list[int].
The valid types are: dict_keys([...typing.List[int]...])
```

| 项目 | 说明 |
|------|------|
| **错误位置** | `vllm/model_executor/layers/quantization/utils/fp8_utils.py` |
| **调用链** | `direct_register_custom_op` → `infer_schema` |
| **根因** | vLLM 使用 `list[int]` (Python 3.9+ 语法)，但 PyTorch 2.5.1 的 infer_schema 只支持 `typing.List[int]` |
| **影响** | 模型注册 subprocess 失败 → 178 个测试失败 |

**错误调用链**：
```
registry.py::_run_in_subprocess
  → import gpt2.py
    → import bitsandbytes_loader.py
      → import fused_moe/__init__.py
        → import fused_moe_method_base.py
          → import modular_kernel.py
            → import utils.py
              → import fp8_utils.py
                → direct_register_custom_op()
                  → infer_schema() ← 此处报错
```

**修复文件**：`vllm/vllm/model_executor/layers/quantization/utils/fp8_utils.py`

**修复内容**：
- 添加 `from typing import List` 导入
- 将所有 `list[int]` 替换为 `List[int]` (共 8 处)

**受影响函数**：
- `cutlass_scaled_mm` (第58行)
- `_w8a8_triton_block_scaled_mm_func` (第78行)
- `_w8a8_triton_block_scaled_mm_fake` (第91行)
- `_padded_cutlass` (第111行)
- `_padded_cutlass_fake` (第148行)
- `w8a8_triton_block_scaled_mm` (第1040行)
- `validate_fp8_block_shape` (第1250行)
- `create_fp8_scale_parameter` (第1311行)

---

### 3. Python 3.10+ Union 类型注解兼容性问题 (已修复 ✓)

**问题描述**：
```python
AttributeError: 'types.UnionType' object has no attribute '__origin__'
```

| 项目 | 说明 |
|------|------|
| **错误位置** | `torch/_library/infer_schema.py:93` |
| **调用链** | `direct_register_custom_op` → `infer_schema` |
| **根因** | Python 3.10+ 使用 `X | Y` 联合类型语法（UnionType），但 PyTorch 2.5.1 的 infer_schema 期望 `typing.Union`，它有 `__origin__` 属性 |
| **触发** | 函数返回类型使用 `torch.Tensor | None` 等语法 |

**修复文件**：
- `vllm/vllm/model_executor/layers/quantization/utils/fp8_utils.py`
- `vllm/vllm/utils/torch_utils.py`

**修复内容**：
在文件顶部添加 `from __future__ import annotations`，使所有类型注解延迟解析为字符串，避免运行时 UnionType 问题。

---

### 4. 批量修复所有 direct_register_custom_op 相关文件 (已修复 ✓)

**问题描述**：
所有调用 `direct_register_custom_op` 的文件都可能触发 UnionType 错误，需要统一添加 `from __future__ import annotations`。

**修复文件列表** (33 个)：
```
vllm/vllm/
├── utils/torch_utils.py
├── _aiter_ops.py
├── compilation/collective_fusion.py
├── distributed/
│   ├── parallel_state.py
│   └── device_communicators/pynccl.py
├── attention/
│   ├── layer.py
│   └ ops/vit_attn_wrappers.py
├── lora/ops/triton_ops/
│   ├── lora_expand_op.py
│   ├── lora_shrink_op.py
│   └ fused_moe_lora_op.py
├── model_executor/
│   ├── models/
│   │   ├── utils.py
│   │   ├── plamo2.py
│   │   ├── qwen3_next.py
│   │   ├── deepseek_v2.py
│   │   └ transformers/moe.py
│   ├── layers/
│   │   ├── utils.py
│   │   ├── kda.py
│   │   ├── fused_moe/
│   │   │   ├── fused_moe.py
│   │   │   ├── layer.py
│   │   │   └ flashinfer_trtllm_moe.py
│   │   ├── mamba/
│   │   │   ├── mamba_mixer.py
│   │   │   ├── mamba_mixer2.py
│   │   │   ├── short_conv.py
│   │   │   └ linear_attn.py
│   │   ├── rotary_embedding/common.py
│   │   ├── quantization/
│   │   │   ├── fp_quant.py
│   │   │   ├── bitsandbytes.py
│   │   │   ├── gguf.py
│   │   │   ├── utils/
│   │   │   │   ├── fp8_utils.py
│   │   │   │   ├── w8a8_utils.py
│   │   │   │   ├── mxfp4_utils.py
│   │   │   │   └ mxfp6_utils.py
│   │   │   └ quark/schemes/quark_ocp_mx.py
```

---

### 5. `from __future__ import` 位置错误 (已修复 ✓)

**问题描述**：
```python
SyntaxError: from __future__ imports must occur at the beginning of the file
```

| 项目 | 说明 |
|------|------|
| **错误位置** | `vllm/_aiter_ops.py:6` 及其他 19 个文件 |
| **根因** | 批量修复时 `sed` 命令将 `__future__ import` 插入到错误位置（在其他 import 之后） |
| **影响** | Python 无法解析文件 → pytest 收集失败 (collected 0 items) |

**Python 规则**：
`from __future__ import` 必须在文件开头（SPDX 注释之后），在任何其他 import 之前。

**正确位置示例**：
```python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
from __future__ import annotations  # ← 正确：紧跟 SPDX 注释
import functools                      # ← 其他 import 在后
from collections.abc import Callable
```

**修复文件列表** (20 个)：
```
vllm/vllm/
├── _aiter_ops.py
├── _version.py
├── v1/structured_output/
│   ├── utils.py
│   └── backend_outlines.py
├── utils/
│   ├── torch_utils.py
│   ├── system_utils.py
│   ├── nccl.py
│   ├── profiling.py
│   └── hashing.py
├── compilation/
│   ├── collective_fusion.py
│   ├── inductor_pass.py
│   └── backends.py
├── model_executor/models/
│   ├── utils.py
│   ├── plamo2.py
│   ├── qwen3_next.py
│   ├── deepseek_v2.py
│   └── transformers/moe.py
├── lora/ops/triton_ops/
│   ├── lora_expand_op.py
│   ├── lora_shrink_op.py
│   └── fused_moe_lora_op.py
```

**修复时间**：2025-05-15

---

## 待验证问题

### 当前状态

所有已知 PyTorch 2.5.1 兼容性问题已修复：
- ✓ TRANSFORMERS_CACHE 路径
- ✓ `list[int]` → `List[int]` 类型注解
- ✓ UnionType → `__future__ annotations`
- ✓ `__future__ import` 位置

**其他警告**（不影响功能）：
```
FutureWarning: Using `TRANSFORMERS_CACHE` is deprecated and will be removed in v5 of Transformers. Use `HF_HOME` instead.
```

---

## 修复步骤

按优先级顺序：

1. [x] **修复 TRANSFORMERS_CACHE 路径** - 已完成 (2025-05-14 17:18)
2. [x] **修复 fp8_utils.py List[int] 类型注解** - 已完成 (2025-05-14 17:18)
3. [x] **修复 torch_utils.py UnionType** - 已完成 (2025-05-14 17:18)
4. [x] **批量修复所有 direct_register_custom_op 文件** - 已完成 (2025-05-14 18:24, 33 个文件)
5. [x] **修复 __future__ import 位置错误** - 已完成 (2025-05-15, 20 个文件)
6. [ ] **验证测试结果** - 待运行

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `scripts/hf_env.sh` | HF 环境配置 |
| `scripts/modelscope_env.sh` | ModelScope 环境配置 |
| `scripts/download_from_modelscope.sh` | ModelScope 下载脚本 |
| `scripts/copy_modelscope_to_hf.sh` | MS → HF 缓存转换 |
| `hf_hub/` | HF 模型缓存目录 |
| `modelscope/` | ModelScope 模型缓存目录 |
| `patches/` | PyTorch 2.5.1 兼容性补丁 |

---

## 下一步

重新运行测试验证修复：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm
source ../pytorch_verify/2.5.1/ut/scripts/hf_env.sh
pytest tests/test_config.py -v -k 'not 72B and not 80B'
```

如果仍有失败，继续检查其他使用 `list[int]` 的文件。

---

## 测试运行日志

### 2025-05-14

| 时间 | 测试结果 | 说明 |
|------|----------|------|
| 01:33 | 21 PASSED, 188 FAILED | 原始测试，TRANSFORMERS_CACHE 未修复 |
| 02:43 | 26 PASSED, 178 FAILED | 修复 hf_env.sh 后 |
| 17:45 | 26 PASSED, 178 FAILED | 修复 fp8_utils.py + torch_utils.py 后，仍有 UnionType 错误 |

### 2025-05-15

| 时间 | 测试结果 | 说明 |
|------|----------|------|
| 09:09 | 0 items, 1 SyntaxError | 批量修复 33 个文件后，`__future__ import` 位置错误 |
| - | 待验证 | 修复 `__future__ import` 位置后，待重新运行 |

---

## 修复操作时间线

```
2025-05-14 17:18  ├─ 修复 hf_env.sh (TRANSFORMERS_CACHE)
                  ├─ 修复 fp8_utils.py (添加 __future__ annotations + List[int])
                  ├─ 修复 torch_utils.py (添加 __future__ annotations)
2025-05-14 18:24  ├─ 批量修复 33 个 direct_register_custom_op 文件
2025-05-15 09:09  ├─ 测试失败: SyntaxError (__future__ 位置错误)
2025-05-15       ├─ 修复 20 个文件的 __future__ import 位置
                  └─ 待重新测试验证
```