#!/bin/bash
# hf_env.sh - HuggingFace 离线环境配置
# 用法: source hf_env.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HF_HUB_DIR="${SCRIPT_DIR}/../hf_hub"

# 设置 HF 环境变量
export HF_HOME="${HF_HUB_DIR}"
export HF_HUB_CACHE="${HF_HUB_DIR}/hub"
export HF_HUB_OFFLINE=1  # 强制离线模式，不联网

# Transformers 缓存 - 指向同一位置，与 HF_HUB_CACHE 共享
# 这样 transformers 库和 huggingface_hub 都从同一缓存加载模型
export TRANSFORMERS_CACHE="${HF_HUB_DIR}/hub"

# HuggingFace Hub 缓存
export HF_DATASETS_CACHE="${HF_HUB_DIR}/datasets"

echo "=============================================="
echo "HuggingFace Offline Environment"
echo "=============================================="
echo ""
echo "Environment variables:"
echo "  HF_HOME          = ${HF_HOME}"
echo "  HF_HUB_CACHE     = ${HF_HUB_CACHE}"
echo "  HF_HUB_OFFLINE   = ${HF_HUB_OFFLINE}"
echo "  TRANSFORMERS     = ${TRANSFORMERS_CACHE}"
echo "  DATASETS         = ${HF_DATASETS_CACHE}"
echo ""
echo "Force offline mode enabled."
echo "Models will only be loaded from local cache."
echo ""
echo "=============================================="
echo "已下载模型"
echo "=============================================="

if [ -d "${HF_HUB_CACHE}" ]; then
    echo ""
    echo "缓存目录: ${HF_HUB_CACHE}"
    echo ""
    echo "已缓存的模型:"
    ls -1 "${HF_HUB_CACHE}" | grep "models--" | sed 's/models--/  /' | sed 's/--/\//'
    echo ""
    echo "总大小:"
    du -sh "${HF_HUB_DIR}" 2>/dev/null || echo "  (计算中...)"
else
    echo ""
    echo "缓存目录不存在: ${HF_HUB_CACHE}"
    echo "请先下载模型:"
    echo "  ./download_test_config_models.sh"
fi

echo ""
echo "=============================================="
echo "测试命令"
echo "=============================================="
echo ""
echo "# 运行所有配置测试（排除大模型）"
echo "pytest tests/test_config.py -v -k 'not 72B and not 80B'"
echo ""
echo "# 运行单个测试"
echo "pytest tests/test_config.py::test_auto_runner -v -k 'distilgpt2'"
echo ""
echo "# 检查模型是否在缓存"
echo "python3 -c \"from huggingface_hub import try_to_load_from_cache; print(try_to_load_from_cache('distilbert/distilgpt2', 'config.json'))\""
echo "=============================================="