#!/usr/bin/env python3
"""JIT 编译 marlin_moe_wna16 算子 (绕过全量 CMake/cutlass 依赖).

背景: _moe_C.abi3.so (2026-05-12) 未包含 2025-12-12 #30254 新增的
moe_wna16_marlin_gemm → 2021 个 test_fused_marlin_moe 全挂.
全量重编译失败 (cutlass v4.2.1 无本地源 + 无外网 clone).
此脚本只编译 csrc/moe/marlin_moe_wna16/ (纯 torch/CUDA, 无 cutlass),
注册到 _moe_C 命名空间 (与现有扩展合并).
"""
from pathlib import Path
from torch.utils.cpp_extension import load

VLLM = Path("/gpfs/gcsp/M2.7_verify/vllm")
MARLIN = VLLM / "csrc/moe/marlin_moe_wna16"

sources = [str(MARLIN / "ops.cu")]
sources += sorted(str(p) for p in MARLIN.glob("sm80_kernel_*.cu"))
sources.append("/gpfs/gcsp/liuxin/apmm/tasks/ut/scripts/marlin_stub.cpp")  # pybind module 入口 (JIT load 需要)
print(f"[build] {len(sources)} 个源文件 (ops.cu + {len(sources)-2} kernels + stub)")

ext = load(
    name="moe_marlin_custom",
    sources=sources,
    extra_include_paths=[
        str(VLLM / "csrc"),
        str(VLLM / "csrc/core"),
    ],
    extra_cuda_cflags=["-DTORCH_EXTENSION_NAME=_moe_C"],
    extra_cflags=["-O3"],
    with_cuda=True,
    verbose=False,
)
print(f"[build] 扩展加载: {ext}")

import torch
print(f"[verify] torch.ops._moe_C.moe_wna16_marlin_gemm: "
      f"{hasattr(torch.ops._moe_C, 'moe_wna16_marlin_gemm')}")
