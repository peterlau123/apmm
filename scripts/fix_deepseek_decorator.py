#!/usr/bin/env python3
"""Fix DeepSeek torch_compile decorator"""
import os

file_path = "/gpfs/gcsp/M2.7_verify/vllm/vllm/model_executor/models/deepseek_v2.py"

with open(file_path, "r") as f:
    content = f.read()

# The decorator needs proper quotes around "input_ids" and "positions"
old_pattern = '@support_torch_compile(dynamic_arg_dims={input_ids: 0, positions: 0})'
new_pattern = '@support_torch_compile(dynamic_arg_dims={"input_ids": 0, "positions": 0})'

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    print(f"Fixed: replaced {old_pattern} with {new_pattern}")
else:
    # Check current state
    for i, line in enumerate(content.split('\n')):
        if '@support_torch_compile' in line and i > 1230 and i < 1240:
            print(f"Line {i+1}: {line}")

with open(file_path, "w") as f:
    f.write(content)

print("Done")