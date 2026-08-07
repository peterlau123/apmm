# 分析 triton 3.1.0 为什么 CUDA 环境误走 AMD 后端
from pathlib import Path

D = Path("/usr/local/lib/python3.12/dist-packages/triton/backends/amd/driver.py")
src = D.read_text()
print("=== HIPDriver 类 + is_active ===")
for i, line in enumerate(src.splitlines(), 1):
    if "class HIPDriver" in line or "def is_active" in line or "def __init__" in line:
        print(f"L{i}: {line.strip()}")
print()
print("=== is_active 方法体 (前后 15 行) ===")
lines = src.splitlines()
for i, line in enumerate(lines):
    if "def is_active" in line:
        start = max(0, i - 2)
        print("\n".join(f"L{s+1}: {lines[s]}" for s in range(start, min(len(lines), i + 18))))
        break
print()
print("=== 模块级代码 (最后一个类后) ===")
tail = "\n".join(f"L{i+1}: {l}" for i, l in enumerate(lines[-15:]))
print(tail)
