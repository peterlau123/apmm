import re

files = [
    "vllm/lora/ops/triton_ops/lora_expand_op.py",
    "vllm/lora/ops/triton_ops/lora_shrink_op.py"
]

for f in files:
    content = open(f).read()
    # Add typing.List import at the top
    if "from typing import List" not in content:
        content = "from typing import List\n" + content
    # Replace list[torch.Tensor] with List[torch.Tensor] in function signatures
    content = re.sub(
        r"lora_(a|b)_weights: list\[torch\.Tensor\]",
        r"lora_\1_weights: List[torch.Tensor]",
        content
    )
    open(f, "w").write(content)
    print(f"Fixed: {f}")

print("Done!")