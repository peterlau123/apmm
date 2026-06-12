# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""PyTorch compatibility layer for older versions (e.g., PyTorch 2.5.1)."""

# PyTorch 2.5.1 does not have auto_functionalized in torch._higher_order_ops
# Create a stub for import compatibility

# ============================================================================
# auto_functionalized compatibility (PyTorch < 2.6)
# ============================================================================
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

# ============================================================================
# wrap_triton compatibility (PyTorch < 2.7)
# ============================================================================
# PyTorch 2.5.1 does not have wrap_triton in torch.library
# Create a stub for import compatibility

import sys

def _inject_wrap_triton():
    """Inject wrap_triton stub into torch.library for compatibility."""
    import torch.library

    if hasattr(torch.library, 'wrap_triton'):
        return  # Already exists, no need to inject

    def wrap_triton_stub(fn):
        """Stub for wrap_triton when PyTorch < 2.7.

        In newer PyTorch, wrap_triton wraps a Triton kernel for use in
        torch.library.define/custom_op. In older versions, we return the
        function unchanged since Triton kernels can still be called directly.
        """
        return fn

    torch.library.wrap_triton = wrap_triton_stub

_inject_wrap_triton()

# ============================================================================
# recompile_limit compatibility (PyTorch < 2.6)
# ============================================================================
# PyTorch 2.5.1 does not have recompile_limit in torch._dynamo.config

def _inject_recompile_limit():
    """Inject recompile_limit stub into torch._dynamo.config."""
    import torch._dynamo

    if hasattr(torch._dynamo.config, 'recompile_limit'):
        return  # Already exists

    # Add a stub attribute that can be read/written but does nothing
    class _StubConfig:
        """Stub for missing config attributes."""
        _value = 16  # Default value used in newer PyTorch

        @property
        def value(self):
            return self._value

        def __setattr__(self, name, value):
            if name == '_value':
                super().__setattr__(name, value)

    # Create a descriptor-like attribute
    torch._dynamo.config.recompile_limit = 16  # Just set a default value

try:
    _inject_recompile_limit()
except Exception:
    pass  # Ignore errors if injection fails