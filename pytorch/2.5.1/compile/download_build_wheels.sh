#!/bin/bash
# vllm build.txt 依赖下载脚本
# 在有网机器上运行，下载 wheel 包供离线安装

set -e

# 输出目录
OUTPUT_DIR="/gpfs/gcsp/M2.7_verify/vllm/wheels/build"

echo "=============================================="
echo "vllm Build Dependencies Download"
echo "=============================================="
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""

# 下载 build.txt 依赖
echo "=== Downloading build.txt dependencies ==="
pip download -r /gpfs/gcsp/M2.7_verify/vllm/requirements/build.txt \
    -d "$OUTPUT_DIR" \
    --python-version 3.12 \
    --only-binary=:all:

echo ""
echo "=============================================="
echo "Download complete!"
echo "=============================================="
echo ""
echo "Wheel packages saved to: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
echo ""
echo "Total files: $(ls "$OUTPUT_DIR"/*.whl 2>/dev/null | wc -l)"
echo ""
echo "On offline machine, run:"
echo "  pip install $OUTPUT_DIR/*.whl"