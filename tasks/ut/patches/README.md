# PyTorch 2.5.1 兼容性修改指南

本文档描述了在 PyTorch 2.5.1 上运行 vLLM 需要的代码修改。

---

## 问题 1: auto_functionalized 不存在

**错误信息**:
```
ImportError: cannot import name 'auto_functionalized' from 'torch._higher_order_ops'
```

**原因**: `auto_functionalized` 是 PyTorch 2.6+ 的内部 API。

### 解决方案

#### 步骤 1: 创建 torch_compat.py

在 `vllm/compilation/` 目录下创建新文件 `torch_compat.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""PyTorch compatibility layer for older versions (e.g., PyTorch 2.5.1)."""

try:
    from torch._higher_order_ops.auto_functionalize import auto_functionalized
except ImportError:
    class _AutoFunctionalizedStub:
        def __call__(self, op, **kwargs):
            import torch
            if torch.compiler.is_compiling():
                raise RuntimeError(
                    "auto_functionalized is not available in PyTorch < 2.6. "
                    "torch.compile graph tracing features are disabled."
                )
            return op(**kwargs)
    auto_functionalized = _AutoFunctionalizedStub()
```

#### 步骤 2: 修改导入语句

修改以下 8 个文件的导入语句:

| 文件 | 原导入 | 新导入 |
|------|--------|--------|
| `vllm/compilation/matcher_utils.py` | `from torch._higher_order_ops import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/fusion_attn.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/fix_functionalization.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/collective_fusion.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/qk_norm_rope_fusion.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/fx_utils.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/fusion.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |
| `vllm/compilation/activation_quant_fusion.py` | `from torch._higher_order_ops.auto_functionalize import auto_functionalized` | `from vllm.compilation.torch_compat import auto_functionalized` |

---

## 问题 2: fresh_cache 不存在

**错误信息**:
```
ImportError: cannot import name 'fresh_cache' from 'torch._inductor.utils'
```

**原因**: `fresh_cache` 是 PyTorch 较新版本添加的功能。

### 解决方案

修改 `tests/conftest.py`:

**第 70 行**:

```python
# 原代码
from torch._inductor.utils import fresh_cache

# 修改为
from contextlib import nullcontext

try:
    from torch._inductor.utils import fresh_cache
except ImportError:
    fresh_cache = nullcontext
```

---

## 问题 3: list[int] 类型注解不支持

**错误信息**:
```
ValueError: infer_schema(func): Parameter output_shape has unsupported type list[int]
```

**原因**: PyTorch 的 `infer_schema` 只支持 `typing.List[int]`，不支持内置泛型 `list[int]`。

### 解决方案

修改 `vllm/distributed/parallel_state.py`:

**第 36 行** - 添加 List 导入:
```python
# 原代码
from typing import Any, Optional

# 修改为
from typing import Any, List, Optional
```

**第 174 行** - 修改类型注解:
```python
# 原代码
output_shape: list[int],

# 修改为
output_shape: List[int],
```

**第 226 行** - 修改类型注解:
```python
# 原代码
output_shape: list[int],

# 修改为
output_shape: List[int],
```

---

## 问题 5: Response API 测试 torch.compile 路径在 torch 2.5.1 崩溃

**错误信息**:
```
InternalTorchDynamoError: _support_torch_compile.<locals>.__call__.<locals>.patched_inline_call() takes 1 positional argument but 4 were given
TypeError: VllmBackend.__call__() got an unexpected keyword argument 'options'
RuntimeError: Server exited unexpectedly.
```

**原因**: vllm commit `eef921f45` "AOT Compilation for torch.compile" 重构了 `_support_torch_compile` 的 monkeypatch（`inline_call_` 单参数形式 + `VllmBackend` 签名），为 torch >=2.7 写的。torch 2.5.1 的 `InliningInstructionTranslator.inline_call_` 仍是 4 参数 `(parent, func, args, kwargs)`，monkeypatch 签名不匹配导致 dynamo 编译崩溃。

Response API 测试 (`test_response_api_*.py`) 默认 `enforce_eager=False`（走 compile），命中崩溃。

### 解决方案（双补丁）

1. **`torch25_inline_call_compat.patch`**: 把 `decorators.py` 的 `patched_inline_call` 回退到 4 参数形式（commit `eef921f45` 之前的写法），兼容 torch 2.5.1 的 `inline_call`/`inline_call_` 签名。这是正确的兼容修复，但单独不够（compile 路径还有 `VllmBackend options` 等更多不匹配）。

2. **`response_api_enforce_eager.patch`**: 给 `test_response_api_simple.py` 和 `test_response_api_parsable_context.py` 的 server args 加 `--enforce-eager`，走 eager 路径彻底绕开 torch 2.5.1 不兼容的 compile 路径。

3. **环境变量** `VLLM_DEEP_GEMM_WARMUP=skip`（加到 `workflow.yaml` 的 `container_env`）: `deep_gemm._C` 未编译（无 `.so`），但 `is_deep_gemm_supported()` 误判 True，warmup 调 `_missing()` 抛错。跳过 warmup 绕开（deep_gemm 本就不可用，无损）。

### 验证

```bash
# Response API 测试（需空闲 GPU + VLLM_DEEP_GEMM_WARMUP=skip）
sudo docker exec -e CUDA_VISIBLE_DEVICES=1 -e VLLM_DEEP_GEMM_WARMUP=skip \
  -e HF_HUB_OFFLINE=1 v0.13.0_torch2.5.1_compile bash -lc \
  'cd /gpfs/gcsp/M2.7_verify/vllm && python3 -m pytest \
   tests/entrypoints/openai/test_response_api_simple.py -q --tb=short'
# 预期: 5/7 passed, 2 个为模型行为断言失败(reasoning/mcp 输出类型), 非崩溃
```

详见 incident 文档 `2026-07-19-generate-batch-normal-starvation-incident.md` Type A 诊断。

---

## 快速应用补丁

在 vllm 源码根目录下运行:

```bash
# 方法 1: 使用脚本
./apply_auto_functionalized_patch.sh

# 方法 2: 使用 patch 命令
patch -p1 < auto_functionalized_compat.patch
patch -p1 < setpgrp_compat.patch

# 方法 3: 手动复制 torch_compat.py
cp torch_compat.py vllm/compilation/
```

---

## 问题 4: docker exec 下 os.setpgrp 权限错误

**错误信息**:
```text
PermissionError: [Errno 1] Operation not permitted
```

**原因**: `docker exec` 启动的 pytest 进程可能成为 session leader，Linux 内核禁止 session leader 调用 `setpgid`/`setpgrp`。

### 解决方案

修改 `tests/utils.py` 中 `fork_new_process_for_each_test()` 的 `os.setpgrp()` 调用：

```python
try:
    os.setpgrp()
except PermissionError:
    pass
```

补丁文件：`setpgrp_compat.patch`

---

## 验证修改

```bash
# 检查导入是否正确
grep -r "auto_functionalized" vllm/compilation/*.py | grep import

# 预期输出: 所有文件都应该从 torch_compat 导入
# vllm/compilation/matcher_utils.py:from vllm.compilation.torch_compat import auto_functionalized
# vllm/compilation/fusion_attn.py:from vllm.compilation.torch_compat import auto_functionalized
# ...

# 测试导入
python -c "from vllm.compilation.backends import VllmBackend"
```

---

## 补丁文件列表

```
patches/
├── torch_compat.py                    # 兼容层文件（复制到 vllm/compilation/）
├── auto_functionalized_compat.patch   # Git patch 文件
├── setpgrp_compat.patch               # docker exec setpgrp 兼容补丁
├── torch25_inline_call_compat.patch   # torch 2.5.1 inline_call 4参数回退补丁
├── response_api_enforce_eager.patch   # Response API 测试加 --enforce-eager
├── apply_auto_functionalized_patch.sh # Shell 脚本
└── README.md                          # 本文档
```