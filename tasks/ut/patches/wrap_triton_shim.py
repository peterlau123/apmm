# 兼容性处理：PyTorch 2.5.1 没有 wrap_triton
try:
    from torch.library import wrap_triton
except ImportError:
    def wrap_triton(func):
        """Shim for wrap_triton in PyTorch 2.5.1"""
        return func