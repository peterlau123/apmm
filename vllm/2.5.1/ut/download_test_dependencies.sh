#!/bin/bash
# vLLM test.txt 依赖下载脚本 - 分层下载
# 使用 --no-cache-dir 直接下载到目标目录，避免占用根目录空间

set -e

OUTPUT_DIR="/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies"
VLLM_DIR="/gpfs/gcsp/M2.7_verify/vllm"

echo "=============================================="
echo "vLLM Test Dependencies Download (Layered)"
echo "=============================================="
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 第一层：核心测试框架（已下载）
echo "=== Layer 1: Core Test Framework ==="
pip download -d "$OUTPUT_DIR" --no-cache-dir --no-deps \
    pytest pytest-forked pytest-asyncio pytest-rerunfailures \
    pytest-shard pytest-timeout pytest-cov tblib httpx 2>&1 || true
echo "✓ Layer 1 downloaded"
echo ""

# 第二层：模型测试依赖（已下载）
echo "=== Layer 2: Model Test Dependencies ==="
pip download -d "$OUTPUT_DIR" --no-cache-dir --no-deps \
    transformers tokenizers peft sentence-transformers 2>&1 || true
echo "✓ Layer 2 downloaded"
echo ""

# 第三层：特定功能测试依赖（已下载）
echo "=== Layer 3: Specific Feature Test Dependencies ==="
# 音频测试
pip download -d "$OUTPUT_DIR" --no-cache-dir --no-deps \
    librosa soundfile jiwer vocos 2>&1 || true
# 视频测试
pip download -d "$OUTPUT_DIR" --no-cache-dir --no-deps \
    opencv-python-headless decord 2>&1 || true
# 量化测试
pip download -d "$OUTPUT_DIR" --no-cache-dir --no-deps \
    bitsandbytes 2>&1 || true
echo "✓ Layer 3 downloaded"
echo ""

# 第四层：完整 test.txt 依赖（可选，耗时较长）
# 如果需要完整依赖，取消下面的注释
# echo "=== Layer 4: Full test.txt Dependencies ==="
# TEMP_REQ=$(mktemp)
# grep -v "^.*@ git+" "$VLLM_DIR/requirements/test.txt" | grep -v "^    # via" | grep -v "^#" | grep -v "^$" > "$TEMP_REQ"
# pip download -r "$TEMP_REQ" -d "$OUTPUT_DIR" --no-cache-dir --no-deps 2>&1 || true
# rm "$TEMP_REQ"
# echo "✓ Layer 4 downloaded"

echo ""
echo "=============================================="
echo "Download complete!"
echo "=============================================="
echo ""
echo "Packages saved to: $OUTPUT_DIR"
ls "$OUTPUT_DIR"/*.whl 2>/dev/null | wc -l | xargs echo "Total wheel files:"
ls "$OUTPUT_DIR"/*.tar.gz 2>/dev/null | wc -l | xargs echo "Total source packages:"
du -sh "$OUTPUT_DIR"
echo ""
echo "Note: git dependencies (lm-eval) need to be cloned separately:"
echo "  cd $OUTPUT_DIR"
echo "  git clone https://github.com/EleutherAI/lm-evaluation-harness.git lm-eval"
echo ""
echo "On offline machine, install with:"
echo "  pip install --no-index --find-links=$OUTPUT_DIR *.whl"