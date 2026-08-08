#!/usr/bin/env python3
"""JIT 编译 _C 的 marlin 补充算子 (gptq_marlin_repack / marlin_int4_fp8_preprocess).

背景 (2026-08-09): 容器 _C.abi3.so 是旧部分编译, 缺一批算子 —
  torch.ops._C.gptq_marlin_repack / marlin_int4_fp8_preprocess 等
  NotImplementedError (CUDA backend 无内核) → marlin_gemm 605 失败。

方案: JIT 编译 gptq_marlin 源 (同 _moe_C 法), TORCH_EXTENSION_NAME=_C
注册到 _C 库 (追加算子), 输出 so 由 vllm 加载 (load_library)。

源 (csrc/quantization/gptq_marlin/):
  gptq_marlin_repack.cu        → gptq_marlin_repack
  marlin_int4_fp8_preprocess.cu → marlin_int4_fp8_preprocess
  gptq_marlin.cu               → gptq_marlin (主算子, 一并编译)
  awq_marlin_repack.cu         → awq_marlin_repack
"""
from pathlib import Path
from torch.utils.cpp_extension import load

VLLM = Path("/gpfs/gcsp/M2.7_verify/vllm")
GQ = VLLM / "csrc/quantization/gptq_marlin"
CUTLASS = Path("/gpfs/gcsp/liuxin/vllm-deps/cutlass-src/include")

sources = [
    str(GQ / "gptq_marlin_repack.cu"),
    str(GQ / "marlin_int4_fp8_preprocess.cu"),
    # gptq_marlin.cu / awq_marlin_repack.cu 需要 torch 2.8 (Float8_e8m0fnu) —
    # torch 2.5.1 无此 dtype → 版本兼容问题, 记录不硬修 (2026-08-09)
    "/gpfs/gcsp/liuxin/apmm/tasks/ut/scripts/stub_c_marlin_extra.cpp",
]

ext = load(
    name="_C_marlin_extra",
    sources=sources,
    extra_include_paths=[
        str(VLLM / "csrc"),
        str(GQ),
        str(VLLM / "csrc/quantization"),
        str(CUTLASS),
    ],
    extra_cflags=["-O3", "-DTORCH_EXTENSION_NAME=_C"],
    extra_cuda_cflags=[
        "-O3",
        "-DTORCH_EXTENSION_NAME=_C",
        "-U__CUDA_NO_HALF_OPERATORS__",
        "-U__CUDA_NO_HALF_CONVERSIONS__",
        "-U__CUDA_NO_BFLOAT16_CONVERSIONS__",
    ],
    verbose=True,
)
print(f"\n[OK] SO: {ext.__file__}")
print("[OK] 检查注册:")
for op in ("gptq_marlin_repack", "marlin_int4_fp8_preprocess", "gptq_marlin", "awq_marlin_repack"):
    print(f"  torch.ops._C.{op}: {hasattr(torch.ops._C, op)}")
