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

## 快速应用补丁

在 vllm 源码根目录下运行:

```bash
# 方法 1: 使用脚本
./apply_auto_functionalized_patch.sh

# 方法 2: 使用 patch 命令
patch -p1 < auto_functionalized_compat.patch

# 方法 3: 手动复制 torch_compat.py
cp torch_compat.py vllm/compilation/
```

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
├── torch_compat.py               # 兼容层文件（复制到 vllm/compilation/）
├── auto_functionalized_compat.patch  # Git patch 文件
├── apply_auto_functionalized_patch.sh # Shell 脚本
└── README.md                     # 本文档
``