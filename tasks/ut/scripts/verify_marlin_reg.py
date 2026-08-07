import importlib.util
import torch

SO = "/root/.cache/torch_extensions/py312_cu124/moe_marlin_custom/moe_marlin_custom.so"
spec = importlib.util.spec_from_file_location("moe_marlin_custom", SO)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print("so 加载成功")

import vllm  # noqa: F401
print("_moe_C 属性:", [n for n in dir(torch.ops._moe_C) if not n.startswith("_")])
try:
    s = torch._C._dispatch_find_schema("_moe_C::moe_wna16_marlin_gemm", "")
    print("schema:", s)
except Exception as e:
    print("schema 查找异常:", type(e).__name__, str(e)[:120])
