import importlib
import torch

try:
    m = importlib.import_module("vllm._moe_C")
    print("vllm._moe_C import 成功:", m)
except Exception as e:
    print("vllm._moe_C import 失败:", type(e).__name__, str(e)[:200])

import vllm  # noqa: F401
print("_moe_C ops:", [n for n in dir(torch.ops._moe_C) if not n.startswith("_")])
