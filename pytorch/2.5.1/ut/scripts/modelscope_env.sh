#!/bin/bash
# modelscope_env.sh - ModelScope 离线环境配置
# 用法: source modelscope_env.sh
#
# vLLM 内置支持 VLLM_USE_MODELSCOPE=true 来从 ModelScope 加载模型
# 参考: vllm/transformers_utils/repo_utils.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELSCOPE_DIR="${SCRIPT_DIR}/../modelscope"

# ModelScope 缓存目录（默认位置）
# ModelScope SDK 使用 MODELSCOPE_CACHE 环境变量
export MODELSCOPE_CACHE="${MODELSCOPE_DIR}"

# 启用 vLLM 的 ModelScope 模式
export VLLM_USE_MODELSCOPE=true

# 禁用 HF 离线模式检查（因为 ModelScope 模式不依赖 HF）
export HF_HUB_OFFLINE=1

echo "=============================================="
echo "vLLM ModelScope Offline Environment"
echo "=============================================="
echo ""
echo "环境变量:"
echo "  VLLM_USE_MODELSCOPE  = ${VLLM_USE_MODELSCOPE}"
echo "  MODELSCOPE_CACHE     = ${MODELSCOPE_CACHE}"
echo "  HF_HUB_OFFLINE       = ${HF_HUB_OFFLINE}"
echo ""
echo "vLLM 将从 ModelScope 缓存加载模型"
echo "=============================================="
echo ""
echo "已缓存的模型:"
if [ -d "${MODELSCOPE_DIR}" ]; then
    ls -1 "${MODELSCOPE_DIR}" | grep "models--" | sed 's/models--/  /' | sed 's/--/\//' | head -20
    echo ""
    echo "总大小:"
    du -sh "${MODELSCOPE_DIR}" 2>/dev/null || echo "  (计算中...)"
else
    echo "  (无缓存，请先下载模型)"
fi

echo ""
echo "=============================================="
echo "下载模型"
echo "=============================================="
echo ""
echo "# 从 ModelScope 下载模型"
echo "python3 -c \""
echo "from modelscope import snapshot_download"
echo "snapshot_download('LLM-Research/Llama-3.2-1B-Instruct', cache_dir='${MODELSCOPE_DIR}')"
echo "\""
echo ""
echo "# 或使用脚本"
echo "./download_from_modelscope.sh"
echo ""
echo "=============================================="
echo "运行测试"
echo "=============================================="
echo ""
echo "# 设置环境后运行测试"
echo "source modelscope_env.sh"
echo "pytest tests/test_config.py -v"
echo ""
echo "# ModelScope 模型 ID 映射:"
echo "# HF: meta-llama/Llama-3.2-1B-Instruct"
echo "# MS: LLM-Research/Llama-3.2-1B-Instruct"
echo "=============================================="