import torch
import vllm  # noqa: F401 加载自定义算子

print("_moe_C 算子:", [n for n in dir(torch.ops._moe_C) if not n.startswith("_")][:8])
try:
    m = torch.ops.moe_marlin_custom
    print("moe_marlin_custom 算子:", [n for n in dir(m) if not n.startswith("_")][:8])
except Exception as e:
    print("moe_marlin_custom 不存在:", e)
print("_moe_C.moe_wna16_marlin_gemm:", hasattr(torch.ops._moe_C, "moe_wna16_marlin_gemm"))
