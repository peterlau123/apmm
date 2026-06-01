#!/bin/bash
# download_models.sh - 统一的模型下载脚本
# 支持 HF 镜像 和 ModelScope 两种源
# 用法: ./download_models.sh [--source hf|ms] [--level N|--all|--check]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HF_HUB_DIR="${SCRIPT_DIR}/../hf_hub"
MODELSCOPE_DIR="${SCRIPT_DIR}/../modelscope"

# 默认使用 HF 镜像（国内网络推荐）
SOURCE="hf"
LEVEL="2"
CHECK_MODE=false

# 解析参数
for arg in "$@"; do
    case $arg in
        --source) ;;
        --level) ;;
        --check) CHECK_MODE=true ;;
        --all) LEVEL="all" ;;
        hf|ms) SOURCE="$arg" ;;
        1|2|3|4|5) LEVEL="$arg" ;;
    esac
done

# 设置缓存目录
if [ "$SOURCE" = "hf" ]; then
    CACHE_DIR="${HF_HUB_DIR}"
    mkdir -p "${CACHE_DIR}/hub"
    export HF_HOME="${CACHE_DIR}"
    export HF_HUB_CACHE="${CACHE_DIR}/hub"
    export HF_ENDPOINT="https://hf-mirror.com"
else
    CACHE_DIR="${MODELSCOPE_DIR}"
    mkdir -p "${CACHE_DIR}"
    export MODELSCOPE_CACHE="${CACHE_DIR}"
fi

echo "=============================================="
echo "vLLM Test Models Downloader"
echo "=============================================="
echo "Source: $SOURCE (${SOURCE}_mirror)"
echo "Cache:  ${CACHE_DIR}"
echo "Level:  ${LEVEL}"
echo "=============================================="

# test_config.py 所需模型（按大小分级）
LEVEL1_MODELS=(
    "distilbert/distilgpt2"
    "facebook/opt-125m"
    "intfloat/e5-small"
    "intfloat/multilingual-e5-small"
    "BAAI/bge-base-en"
    "BAAI/bge-base-en-v1.5"
    "BAAI/bge-reranker-base"
    "sentence-transformers/all-MiniLM-L12-v2"
    "cross-encoder/ms-marco-MiniLM-L-6-v2"
    "openai/whisper-tiny"
    "openai/clip-vit-base-patch32"
    "google/siglip-base-patch16-224"
    "state-spaces/mamba-130m-hf"
    "boltuix/NeuroBERT-NER"
    "papluca/xlm-roberta-base-language-detection"
)

LEVEL2_MODELS=(
    "Qwen/Qwen2.5-1.5B-Instruct"
    "Qwen/Qwen3-0.6B"
    "Qwen/Qwen3-Embedding-0.6B"
    "tomaarsen/Qwen3-Reranker-0.6B-seq-cls"
    "meta-llama/Llama-3.2-1B-Instruct"
    "openai/whisper-small"
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
    "internlm/internlm2-1_8b-reward"
    "jason9693/Qwen2.5-1.5B-apeach"
)

LEVEL3_MODELS=(
    "Qwen/Qwen2.5-Math-PRM-7B"
    "Qwen/Qwen2-VL-2B-Instruct"
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
    "ibm-granite/granite-4.0-h-small"
)

LEVEL4_MODELS=(
    "Qwen/Qwen1.5-7B"
    "mistralai/Mistral-7B-v0.1"
    "mistralai/Mistral-7B-Instruct-v0.2"
    "meta-llama/Meta-Llama-3-8B-Instruct"
    "deepseek-ai/DeepSeek-V2-Lite"
    "lmsys/longchat-13b-16k"
    "RedHatAI/Llama-3.1-8B-Instruct-NVFP4"
    "RedHatAI/Llama-3.2-1B-FP8"
    "RedHatAI/Qwen3-8B-speculator.eagle3"
)

LEVEL5_MODELS=(
    "Qwen/Qwen2.5-Math-RM-72B"
    "Qwen/Qwen3-Next-80B-A3B-Instruct"
    "RedHatAI/Llama-4-Scout-17B-16E-Instruct"
    "RedHatAI/Mixtral-8x7B-Instruct-v0.1"
    "RedHatAI/DeepSeek-V2.5-1210-FP8"
    "RedHatAI/gpt-oss-20b"
    "RedHatAI/Mistral-Small-24B-Instruct-2501-quantized.w8a8"
)

# 构建下载列表
case $LEVEL in
    1) MODELS=("${LEVEL1_MODELS[@]}") ;;
    2) MODELS=("${LEVEL1_MODELS[@]}" "${LEVEL2_MODELS[@]}") ;;
    3) MODELS=("${LEVEL1_MODELS[@]}" "${LEVEL2_MODELS[@]}" "${LEVEL3_MODELS[@]}") ;;
    4) MODELS=("${LEVEL1_MODELS[@]}" "${LEVEL2_MODELS[@]}" "${LEVEL3_MODELS[@]}" "${LEVEL4_MODELS[@]}") ;;
    5) MODELS=("${LEVEL1_MODELS[@]}" "${LEVEL2_MODELS[@]}" "${LEVEL3_MODELS[@]}" "${LEVEL4_MODELS[@]}" "${LEVEL5_MODELS[@]}") ;;
    all) MODELS=("${LEVEL1_MODELS[@]}" "${LEVEL2_MODELS[@]}" "${LEVEL3_MODELS[@]}" "${LEVEL4_MODELS[@]}" "${LEVEL5_MODELS[@]}") ;;
    *) echo "Usage: $0 [--source hf|ms] [--level N|--all|--check]"; exit 1 ;;
esac

# 检查缓存
is_cached() {
    local model_id="$1"
    local org=$(echo "$model_id" | cut -d/ -f1)
    local model=$(echo "$model_id" | cut -d/ -f2)

    if [ "$SOURCE" = "hf" ]; then
        [ -d "${HF_HUB_CACHE}/models--${org}--${model}/snapshots" ] && \
        [ $(find "${HF_HUB_CACHE}/models--${org}--${model}/snapshots" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l) -gt 0 ]
    else
        # ModelScope: 支持 org/model 和 models--org--model 两种结构
        [ -d "${MODELSCOPE_DIR}/${org}/${model}" ] && [ -f "${MODELSCOPE_DIR}/${org}/${model}/config.json" ] || \
        [ -d "${MODELSCOPE_DIR}/models--${org}--${model}/snapshots" ]
    fi
}

# 下载函数
download_model() {
    local model_id="$1"
    local current="$2"
    local total="$3"

    echo ""
    echo "[${current}/${total}] Downloading: ${model_id}"

    if [ "$SOURCE" = "hf" ]; then
        python3 -c "
from huggingface_hub import snapshot_download
import os, sys
try:
    path = snapshot_download(repo_id='${model_id}', cache_dir=os.environ['HF_HUB_CACHE'])
    print(f'  ✓ Saved to: {path}')
    sys.exit(0)
except Exception as e:
    print(f'  ✗ Error: {e}')
    sys.exit(1)
" 2>&1
    else
        python3 -c "
from modelscope import snapshot_download
import os, sys
try:
    path = snapshot_download(model_id='${model_id}', cache_dir=os.environ['MODELSCOPE_CACHE'])
    print(f'  ✓ Saved to: {path}')
    sys.exit(0)
except Exception as e:
    print(f'  ✗ Error: {e}')
    sys.exit(1)
" 2>&1
    fi

    [ $? -eq 0 ]
}

echo ""
echo "Total models: ${#MODELS[@]}"
echo ""

# 检查缓存状态
SKIPPED=0
TO_DOWNLOAD=()

for model in "${MODELS[@]}"; do
    if is_cached "$model"; then
        echo "  ✓ Cached: $model"
        SKIPPED=$((SKIPPED + 1))
    else
        TO_DOWNLOAD+=("$model")
    fi
done

echo ""
echo "Cached: ${SKIPPED}, To download: ${#TO_DOWNLOAD[@]}"

if [ ${#TO_DOWNLOAD[@]} -eq 0 ]; then
    echo ""
    echo "All models cached!"
    du -sh "${CACHE_DIR}"
    exit 0
fi

if [ "$CHECK_MODE" = true ]; then
    echo ""
    echo "To download missing models: ./download_models.sh --source $SOURCE --level $LEVEL"
    exit 0
fi

echo ""
echo "Models to download:"
for model in "${TO_DOWNLOAD[@]}"; do echo "  - $model"; done

echo ""
read -p "Start download? (y/n) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && echo "Cancelled." && exit 0

# 执行下载
CURRENT=0
SUCCESS=0
FAILED=0

for model in "${TO_DOWNLOAD[@]}"; do
    CURRENT=$((CURRENT + 1))
    download_model "$model" $CURRENT ${#TO_DOWNLOAD[@]} && SUCCESS=$((SUCCESS + 1)) || FAILED=$((FAILED + 1))
done

echo ""
echo "=============================================="
echo "Download Complete"
echo "=============================================="
echo "Success: ${SUCCESS}, Failed: ${FAILED}"
echo ""
du -sh "${CACHE_DIR}"
echo ""
echo "Offline usage: source ${SCRIPT_DIR}/hf_env.sh"
echo "Run tests: pytest tests/test_config.py -v -k 'not 72B and not 80B'"
echo "=============================================="