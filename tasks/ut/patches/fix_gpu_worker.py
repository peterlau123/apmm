#!/usr/bin/env python3
"""Fix gpu_worker.py fp32_precision indentation for PyTorch 2.5.1"""

import os

file_path = "/gpfs/gcsp/M2.7_verify/vllm/vllm/v1/worker/gpu_worker.py"

# Read the file
with open(file_path, "r") as f:
    content = f.read()

# Find and fix the problematic section
# The issue: the hasattr check line needs proper indentation inside __init__
# and the line inside the if block needs additional indentation

old_pattern = """        precision = envs.VLLM_FLOAT32_MATMUL_PRECISION
        if hasattr(torch.backends.cuda.matmul, "fp32_precision"):
torch.backends.cuda.matmul.fp32_precision = precision"""

new_pattern = """        precision = envs.VLLM_FLOAT32_MATMUL_PRECISION
        if hasattr(torch.backends.cuda.matmul, "fp32_precision"):
            torch.backends.cuda.matmul.fp32_precision = precision"""

# Alternative: check if the old direct assignment exists (without hasattr)
old_direct = "        torch.backends.cuda.matmul.fp32_precision = precision"

if old_direct in content and "if hasattr" not in content[:content.find(old_direct)+500]:
    # Original code exists, apply the fix
    content = content.replace(old_direct, """        if hasattr(torch.backends.cuda.matmul, "fp32_precision"):
            torch.backends.cuda.matmul.fp32_precision = precision
        # PyTorch 2.5.1 compatibility: fp32_precision not available""")
    print("Applied fix for original code")
elif old_pattern in content:
    # Fix the indentation
    content = content.replace(old_pattern, new_pattern)
    print("Fixed indentation issue")
elif "if hasattr(torch.backends.cuda.matmul, \"fp32_precision\"):" in content:
    # Check if indentation is correct
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "if hasattr(torch.backends.cuda.matmul, \"fp32_precision\"):" in line:
            indent = len(line) - len(line.lstrip())
            next_line = lines[i+1] if i+1 < len(lines) else ""
            next_indent = len(next_line) - len(next_line.lstrip())
            if next_indent <= indent:
                # Fix the indentation
                lines[i+1] = " " * (indent + 4) + next_line.lstrip()
                print(f"Fixed line {i+2}: needed {indent+4} spaces, had {next_indent}")
    content = "\n".join(lines)
else:
    print("No known pattern found, checking file content...")
    # Find the line
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "fp32_precision" in line:
            print(f"Line {i+1}: {line}")

# Write the fixed content
with open(file_path, "w") as f:
    f.write(content)

print(f"Fixed {file_path}")