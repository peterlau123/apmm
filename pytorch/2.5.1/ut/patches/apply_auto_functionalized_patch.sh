#!/bin/bash
# apply_auto_functionalized_patch.sh - 应用 auto_functionalized 兼容补丁
# 在 vllm 源码根目录下运行此脚本

set -e

echo "=============================================="
echo "Applying auto_functionalized compatibility patch"
echo "=============================================="

# 检查是否在 vllm 目录
if [ ! -d "vllm/compilation" ]; then
    echo "ERROR: Please run this script in vllm source root directory"
    echo "Expected directory structure: vllm/compilation/"
    exit 1
fi

# 1. 创建 torch_compat.py
echo "Creating torch_compat.py..."
cat > vllm/compilation/torch_compat.py << 'EOF'
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""PyTorch compatibility layer for older versions (e.g., PyTorch 2.5.1)."""

# PyTorch 2.5.1 does not have auto_functionalized in torch._higher_order_ops
# Create a stub for import compatibility

try:
    from torch._higher_order_ops.auto_functionalize import auto_functionalized
except ImportError:
    # Stub for older PyTorch versions
    # This allows imports to succeed but compilation features will not work
    # When torch.compile is actually used, it will raise RuntimeError
    class _AutoFunctionalizedStub:
        """Stub for auto_functionalized when PyTorch < 2.6"""

        def __call__(self, op, **kwargs):
            # During compilation phase, this should not be called
            # If called outside compilation, try direct execution
            import torch
            if torch.compiler.is_compiling():
                raise RuntimeError(
                    "auto_functionalized is not available in PyTorch < 2.6. "
                    "torch.compile graph tracing features are disabled for this PyTorch version."
                )
            # Fallback: execute the operation directly (not correct for graph tracing)
            return op(**kwargs)

    auto_functionalized = _AutoFunctionalizedStub()
EOF
echo "  -> vllm/compilation/torch_compat.py created"

# 2. 修改 matcher_utils.py
echo "Patching matcher_utils.py..."
if grep -q "from torch._higher_order_ops import auto_functionalized" vllm/compilation/matcher_utils.py; then
    sed -i 's/from torch._higher_order_ops import auto_functionalized/from vllm.compilation.torch_compat import auto_functionalized/' vllm/compilation/matcher_utils.py
    echo "  -> matcher_utils.py patched (import style 1)"
elif grep -q "from torch._higher_order_ops.auto_functionalize import auto_functionalized" vllm/compilation/matcher_utils.py; then
    sed -i 's/from torch._higher_order_ops.auto_functionalize import auto_functionalized/from vllm.compilation.torch_compat import auto_functionalized/' vllm/compilation/matcher_utils.py
    echo "  -> matcher_utils.py patched (import style 2)"
else
    echo "  -> matcher_utils.py already patched or different import style"
fi

# 3. 修改其他文件（使用统一的导入路径）
for file in \
    vllm/compilation/fusion_attn.py \
    vllm/compilation/fix_functionalization.py \
    vllm/compilation/collective_fusion.py \
    vllm/compilation/qk_norm_rope_fusion.py \
    vllm/compilation/fx_utils.py \
    vllm/compilation/fusion.py \
    vllm/compilation/activation_quant_fusion.py
do
    echo "Patching $file..."
    if [ -f "$file" ]; then
        if grep -q "from torch._higher_order_ops" "$file"; then
            sed -i 's/from torch\._higher_order_ops\.auto_functionalize import auto_functionalized/from vllm.compilation.torch_compat import auto_functionalized/' "$file"
            sed -i 's/from torch\._higher_order_ops import auto_functionalized/from vllm.compilation.torch_compat import auto_functionalized/' "$file"
            echo "  -> $file patched"
        else
            echo "  -> $file already patched or no match"
        fi
    else
        echo "  -> $file not found, skipping"
    fi
done

echo ""
echo "=============================================="
echo "Patch applied successfully!"
echo "=============================================="
echo ""
echo "Files modified:"
echo "  - vllm/compilation/torch_compat.py (created)"
echo "  - vllm/compilation/matcher_utils.py"
echo "  - vllm/compilation/fusion_attn.py"
echo "  - vllm/compilation/fix_functionalization.py"
echo "  - vllm/compilation/collective_fusion.py"
echo "  - vllm/compilation/qk_norm_rope_fusion.py"
echo "  - vllm/compilation/fx_utils.py"
echo "  - vllm/compilation/fusion.py"
echo "  - vllm/compilation/activation_quant_fusion.py"
echo ""
echo "To verify, run:"
echo "  grep -r 'auto_functionalized' vllm/compilation/*.py | grep import"