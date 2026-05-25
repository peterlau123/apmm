#!/bin/bash
# vLLM 离线编译脚本
# 在离线机器上运行，使用预下载的依赖仓库

set -e

# 编译控制选项
CLEAN_CACHE=${CLEAN_CACHE:-"true"}  # 是否清理编译缓存（默认清理）

echo "=============================================="
echo "vLLM Offline Build Script"
echo "=============================================="
echo ""

export MAX_JOBS=16
export NVCC_THREADS=1

# 设置工作目录
VLLM_DIR="/gpfs/gcsp/M2.7_verify/vllm"
DEPS_DIR="/gpfs/gcsp/M2.7_verify/vllm/.deps"
WHEELS_DIR="/gpfs/gcsp/M2.7_verify/vllm/wheels/build"

cd "$VLLM_DIR"

# Step 0: 清理编译缓存（可选）
echo "=== Step 0: Build Cache Control ==="
echo "CLEAN_CACHE=$CLEAN_CACHE"

if [ "$CLEAN_CACHE" = "true" ]; then
    echo "Cleaning build cache..."

    # 清理 Python build 缓存
    rm -rf build/ dist/ *.egg-info vllm.egg-info/ .eggs/
    rm -rf vllm/_C/*.so vllm/_C/*.pyd

    # 清理 .deps 目录下的构建产物（保留源码）
    rm -rf "$DEPS_DIR"/*-build/ "$DEPS_DIR"/*-subbuild/
    rm -rf "$DEPS_DIR"/CMakeCache.txt "$DEPS_DIR"/CMakeFiles/

    # 清理 pip 临时缓存
    rm -rf /tmp/pip-ephem-wheel-cache-* 2>/dev/null || true

    echo "✓ Build cache cleaned"
else
    echo "Skipping cache clean (CLEAN_CACHE=false)"
    echo "Note: If CMAKE_ARGS changed, you may need to clean cache manually"
fi

echo ""

# Step 1: 安装 build 依赖
echo "=== Step 1: Installing build dependencies ==="
if ls "$WHEELS_DIR/*.whl" 1>/dev/null 2>&1; then
    pip install "$WHEELS_DIR/*.whl"
    echo "✓ Build dependencies installed"
else
    echo "⚠ No wheel packages found in $WHEELS_DIR"
    echo "  Please run download_build_wheels.sh on a machine with internet access"
fi

echo ""

# Step 2: 设置所有依赖的环境变量
echo "=== Step 2: Setting environment variables ==="

# 版本号（跳过 git 检测）
export SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0"
echo "SETUPTOOLS_SCM_PRETEND_VERSION=$SETUPTOOLS_SCM_PRETEND_VERSION"

# CUDA 编译依赖
export VLLM_CUTLASS_SRC_DIR="$DEPS_DIR/cutlass-src"
export VLLM_FLASH_ATTN_SRC_DIR="$DEPS_DIR/flash-attention-src"
export FLASH_MLA_SRC_DIR="$DEPS_DIR/FlashMLA-src"
export QUTLASS_SRC_DIR="$DEPS_DIR/qutlass-src"

# triton_kernels: 使用 vLLM 自定义变量，指向 Python 子目录
# 注意：必须指向 triton_kernels python 目录，而非 triton 根目录
export TRITON_KERNELS_SRC_DIR="$DEPS_DIR/triton-src/python/triton_kernels/triton_kernels"

# CMake 参数：禁用 triton unittest 和 Marlin kernels（PyTorch 2.5.1 兼容性问题）
# Marlin kernels 需要 Float8_e8m0fnu ScalarType，PyTorch 2.5.1 不支持
export CMAKE_ARGS="-DTRITON_BUILD_UT=OFF -DVLLM_DISABLE_MARLIN=ON"

echo "VLLM_CUTLASS_SRC_DIR=$VLLM_CUTLASS_SRC_DIR"
echo "VLLM_FLASH_ATTN_SRC_DIR=$VLLM_FLASH_ATTN_SRC_DIR"
echo "FLASH_MLA_SRC_DIR=$FLASH_MLA_SRC_DIR"
echo "QUTLASS_SRC_DIR=$QUTLASS_SRC_DIR"
echo "TRITON_KERNELS_SRC_DIR=$TRITON_KERNELS_SRC_DIR"
echo "CMAKE_ARGS=$CMAKE_ARGS"

# 检查依赖目录是否存在
echo ""
echo "=== Step 3: Checking dependency directories ==="

DEPS_OK=true

for dep in cutlass-src triton-src flash-attention-src FlashMLA-src qutlass-src; do
    if [ -d "$DEPS_DIR/$dep" ]; then
        size=$(du -sh "$DEPS_DIR/$dep" | cut -f1)
        echo "✓ $dep exists ($size)"
    else
        echo "✗ $dep NOT FOUND"
        DEPS_OK=false
    fi
done

if [ "$DEPS_OK" = false ]; then
    echo ""
    echo "⚠ Missing dependencies. Please download them on a machine with internet access:"
    echo ""
    echo "  cd $DEPS_DIR"
    echo "  git clone --depth 1 --branch v4.2.1 https://github.com/nvidia/cutlass.git cutlass-src"
    echo "  git clone --depth 1 --branch v3.5.0 https://github.com/triton-lang/triton.git triton-src"
    echo "  git clone --depth 1 https://github.com/vllm-project/flash-attention.git flash-attention-src"
    echo "  git clone --depth 1 https://github.com/vllm-project/FlashMLA.git FlashMLA-src"
    echo "  git clone --depth 1 https://github.com/IST-DASLab/qutlass.git qutlass-src"
    echo ""
    exit 1
fi

echo ""

# Step 4: 显示编译控制选项
echo "=== Step 4: Build Control Options ==="
echo ""
echo "Compilation Features:"
echo "  • TRITON_BUILD_UT=OFF      (禁用 Triton unittest，避免 googletest 依赖)"
echo "  • VLLM_DISABLE_MARLIN=ON   (禁用 Marlin kernels，PyTorch 2.5.1 兼容性)"
echo ""
echo "Disabled Kernel Modules:"
echo "  • gptq_marlin              (量化 kernel，需要 Float8_e8m0fnu)"
echo "  • marlin_24                (稀疏量化 kernel)"
echo "  • marlin_moe_wna16         (MOE 量化 kernel)"
echo ""
echo "Enabled Kernel Modules:"
echo "  • flash-attention          (注意力机制 kernel)"
echo "  • FlashMLA                 (MLA 注意力 kernel，sm90a)"
echo "  • cutlass                  (矩阵运算 kernel)"
echo "  • triton_kernels           (Python triton kernels)"
echo ""
echo "CUDA Architecture: sm_90 (Hopper)"
echo "PyTorch Version: 2.5.1+cu124"
echo ""

# Step 5: 编译安装
echo "=== Step 5: Building vLLM ==="
echo "This may take a while..."
echo ""

pip install -e . --no-build-isolation 2>&1 | tee "$VLLM_DIR/install.log"

echo ""
echo "=============================================="
echo "Build complete!"
echo "=============================================="
echo ""
echo "Log saved to: $VLLM_DIR/install.log"
echo ""
echo "To verify installation:"
echo "  python -c 'import vllm; print(vllm.__version__)'"
