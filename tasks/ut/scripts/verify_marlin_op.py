import torch
import vllm  # noqa: F401

ops = [n for n in dir(torch.ops._moe_C) if not n.startswith("_")]
print("_moe_C 属性数:", len(ops))
# hasattr 验证关键算子
for name in ("moe_wna16_marlin_gemm", "topk_softmax", "moe_sum",
             "grouped_topk", "moe_align_block_size", "shuffle_rows",
             "moe_align_sum", "moe_lora_align_block_size"):
    print(f"  {name}: {hasattr(torch.ops._moe_C, name)}")
