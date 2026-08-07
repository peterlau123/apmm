#!/usr/bin/env python3
"""JIT 编译完整 _moe_C 扩展 (绕过全量 CMake: cutlass/triton/MLIR 依赖).

背景:
- 全量重编译受阻: cutlass/trtiton 无外网 clone (已本地化 5 个依赖, 但 triton
  编译需 MLIR 开发库, 容器无外网无法安装)
- _moe_C 全部源文件纯 torch/CUDA (无 cutlass/triton/MLIR 依赖) → JIT 可行
- 完整 _moe_C 含 torch_bindings.cpp 的 TORCH_LIBRARY(_moe_C) 注册 (schema+impl),
  ops.cu 的 marlin 走 TORCH_LIBRARY_IMPL 追加 → 库存在时注册正常
  (之前单独编 marlin 注册空 = 库不存在)

源文件 (来自 CMakeLists.txt L951-975):
  csrc/moe/torch_bindings.cpp
  csrc/moe/moe_align_sum_kernels.cu
  csrc/moe/topk_softmax_kernels.cu
  csrc/moe/moe_wna16.cu
  csrc/moe/grouped_topk_kernels.cu
  csrc/moe/moe_permute_unpermute_kernels/moe_permute_unpermute_kernel.cu
  csrc/moe/moe_permute_unpermute_op.cu
  + marlin_moe_wna16 (ops.cu + 14 sm80_kernel_*.cu)
  + marlin_stub.cpp (PyInit 入口)
"""
from pathlib import Path
from torch.utils.cpp_extension import load

VLLM = Path("/gpfs/gcsp/M2.7_verify/vllm")
MOE = VLLM / "csrc/moe"
MARLIN = MOE / "marlin_moe_wna16"

sources = [
    str(MOE / "torch_bindings.cpp"),
    str(MOE / "moe_align_sum_kernels.cu"),
    str(MOE / "topk_softmax_kernels.cu"),
    str(MOE / "moe_wna16.cu"),
    str(MOE / "grouped_topk_kernels.cu"),
    str(MOE / "permute_unpermute_kernels/moe_permute_unpermute_kernel.cu"),
    str(MOE / "moe_permute_unpermute_op.cu"),
]
sources.append(str(MARLIN / "ops.cu"))
sources += sorted(str(p) for p in MARLIN.glob("sm80_kernel_*.cu"))
# 注: torch_bindings.cpp 自带 PYBIND11_MODULE(TORCH_EXTENSION_NAME) — 不需要 stub
print(f"[build] {len(sources)} 个源文件 (完整 _moe_C + marlin)")

ext = load(
    name="moe_marlin_custom",
    sources=sources,
    extra_include_paths=[
        str(VLLM / "csrc"),
        str(VLLM / "csrc/core"),
        "/gpfs/gcsp/liuxin/vllm-deps/cutlass-src/include",  # cutlass 头 (permute_unpermute 依赖)
    ],
    extra_cuda_cflags=[
        "-DTORCH_EXTENSION_NAME=_moe_C",
        # JIT 默认禁用 half 转换宏, cutlass 4.2.1 头依赖 half->float 转换 → 取消
        "-U__CUDA_NO_HALF_OPERATORS__",
        "-U__CUDA_NO_HALF_CONVERSIONS__",
        "-U__CUDA_NO_BFLOAT16_CONVERSIONS__",
    ],
    # torch_bindings.cpp 的 PYBIND11_MODULE(TORCH_EXTENSION_NAME) → PyInit__moe_C
    # (替换 vllm/_moe_C.abi3.so 后 python 原生加载需要)
    extra_cflags=["-O3", "-DTORCH_EXTENSION_NAME=_moe_C"],
    with_cuda=True,
    verbose=False,
)
print(f"[build] 扩展加载: {ext}")

import torch
print("[verify] _moe_C ops:",
      [n for n in dir(torch.ops._moe_C) if not n.startswith("_")][:12])
print("[verify] marlin:", hasattr(torch.ops._moe_C, "moe_wna16_marlin_gemm"))
print("[verify] topk_softmax:", hasattr(torch.ops._moe_C, "topk_softmax"))
