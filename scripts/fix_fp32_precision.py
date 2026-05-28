#!/usr/bin/env python3
"""Fix fp32_precision attribute for PyTorch 2.5.1 compatibility"""

file_path = "vllm/v1/worker/gpu_worker.py"

with open(file_path, "r") as f:
    content = f.read()

# Replace the problematic line
old_line = "torch.backends.cuda.matmul.fp32_precision = precision"
new_lines = """if hasattr(torch.backends.cuda.matmul, 'fp32_precision'):
            torch.backends.cuda.matmul.fp32_precision = precision
        # PyTorch 2.5.1: fp32_precision attribute not available"""

content = content.replace(old_line, new_lines)

with open(file_path, "w") as f:
    f.write(content)

print("Fixed gpu_worker.py")