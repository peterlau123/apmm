#!/bin/bash
# LoRA类型签名修复脚本
# 将list[torch.Tensor]改为List[torch.Tensor]以兼容PyTorch infer_schema

set -e

VLLM_DIR="/gpfs/gcsp/M2.7_verify/vllm"

# 需要修复的文件列表
FILES=(
    "vllm/lora/ops/triton_ops/lora_expand_op.py"
    "vllm/lora/ops/triton_ops/lora_shrink_op.py"
    "vllm/lora/ops/triton_ops/fused_moe_lora_op.py"
)

# 检查是否已经在正确的分支
cd "$VLLM_DIR"
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "2.5.1_ut_verify" ]; then
    echo "Error: Not on 2.5.1_ut_verify branch"
    exit 1
fi

# 备份原始文件
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        cp "$file" "${file}.bak"
        echo "Backed up: $file"
    fi
done

# 应用修复
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        # 检查是否已有typing.List导入
        if ! grep -q "from typing import.*List" "$file"; then
            # 在__future__ import后添加typing.List导入
            sed -i '/from __future__ import annotations/a from typing import List' "$file"
            echo "Added List import to: $file"
        fi

        # 在fake函数定义中替换list[torch.Tensor]为List[torch.Tensor]
        # 只替换函数参数中的类型注解，不替换注释中的
        sed -i 's/lora_b_weights: list\[torch\.Tensor\]/lora_b_weights: List[torch.Tensor]/g' "$file"
        sed -i 's/lora_a_weights: list\[torch\.Tensor\]/lora_a_weights: List[torch.Tensor]/g' "$file"
        sed -i 's/lora_a_stacked: list\[torch\.Tensor\]/lora_a_stacked: List[torch.Tensor]/g' "$file"
        sed -i 's/lora_b_stacked: list\[torch\.Tensor\]/lora_b_stacked: List[torch.Tensor]/g' "$file"
        echo "Fixed type annotations in: $file"
    fi
done

echo "Done! Please verify the changes and commit."