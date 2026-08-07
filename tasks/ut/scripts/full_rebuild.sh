#!/bin/bash
# 全量重编译 vllm v2 (export 环境变量, 确认本地源生效)
DEPS=/gpfs/gcsp/liuxin/vllm-deps
cd /gpfs/gcsp/M2.7_verify/vllm || exit 1

for p in $(pgrep -f 'setup.py build_ext'); do
  [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null
done
sleep 2
rm -rf build .deps /tmp/vllm_full_rebuild.log

export VLLM_CUTLASS_SRC_DIR="$DEPS/cutlass-src"
export TRITON_KERNELS_SRC_DIR="$DEPS/triton-src"
export FLASH_MLA_SRC_DIR="$DEPS/flashmla-src"
export FETCHCONTENT_SOURCE_DIR_QUTLASS="$DEPS/qutlass-src"
export GOOGLETEST_SRC_DIR="$DEPS/googletest-src"

echo "=== 依赖源确认 ==="
echo "  VLLM_CUTLASS_SRC_DIR=$VLLM_CUTLASS_SRC_DIR"
echo "  TRITON_KERNELS_SRC_DIR=$TRITON_KERNELS_SRC_DIR"
echo "  FLASH_MLA_SRC_DIR=$FLASH_MLA_SRC_DIR"
echo "  FETCHCONTENT_SOURCE_DIR_QUTLASS=$FETCHCONTENT_SOURCE_DIR_QUTLASS"
echo "  GOOGLETEST_SRC_DIR=$GOOGLETEST_SRC_DIR"
ls "$DEPS/triton-src/python/triton" >/dev/null && echo "  triton-src: OK"
ls "$DEPS/cutlass-src/include/cutlass/version.h" >/dev/null && echo "  cutlass-src: OK"

echo "=== 启动编译 ==="
nohup python3 setup.py build_ext --inplace > /tmp/vllm_full_rebuild.log 2>&1 &
echo "started-pid=$!"
