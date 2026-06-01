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