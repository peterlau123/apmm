import importlib
import torch

try:
    m = importlib.import_module("vllm._moe_C")
    print("vllm._moe_C import OK:", m)
except Exception as e:
    print("vllm._moe_C import 失败:", type(e).__name__, str(e)[:200])

print("torch.ops._moe_C:", [n for n in dir(torch.ops._moe_C) if not n.startswith("_")])
print("marlin:", hasattr(torch.ops._moe_C, "moe_wna16_marlin_gemm"))
