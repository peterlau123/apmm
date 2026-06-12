#!/bin/bash
# MiniMax-M2.7 evalscope 评测脚本
# 支持的数据集：gsm8k, gpqa_diamond, math_500, ifeval, mmlu_pro, live_code_bench
#
# 用法：
#   bash run_evalscope.sh                      # 默认使用 gpqa_diamond
#   bash run_evalscope.sh gpqa_diamond         # 指定单个数据集
#   bash run_evalscope.sh gsm8k math_500       # 指定多个数据集
#   bash run_evalscope.sh all                  # 运行全部数据集

set -e

# 默认数据集
DEFAULT_DATASET="gpqa_diamond"

# 支持的全部数据集
ALL_DATASETS="gsm8k gpqa_diamond math_500 ifeval mmlu_pro live_code_bench"

# 解析参数
DATASETS="${@:-$DEFAULT_DATASET}"

# 如果参数是 "all"，则使用全部数据集
if [ "$DATASETS" = "all" ]; then
    DATASETS="$ALL_DATASETS"
fi

# 创建日志目录
mkdir -p ./log

# 生成日志文件名（包含数据集信息）
DATASET_TAG=$(echo "$DATASETS" | tr ' ' '_')
LOG_TIME=$(date +%F-%H%M)

echo "=============================================="
echo "MiniMax-M2.7 Evalscope Benchmark"
echo "=============================================="
echo ""
echo "Model: MiniMax-M2.7"
echo "API URL: http://127.0.0.1:9527/v1/chat/completions"
echo "Datasets: $DATASETS"
echo "Eval batch size: 32"
echo ""

# 显示帮助信息
show_help() {
    echo "用法："
    echo "  bash run_evalscope.sh                      # 默认使用 gpqa_diamond"
    echo "  bash run_evalscope.sh <dataset>            # 指定单个数据集"
    echo "  bash run_evalscope.sh <dataset1> <dataset2> # 指定多个数据集"
    echo "  bash run_evalscope.sh all                  # 运行全部数据集"
    echo ""
    echo "支持的数据集："
    echo "  gsm8k          - GSM8K 数学题"
    echo "  gpqa_diamond   - GPQA Diamond 科学问答"
    echo "  math_500       - MATH-500 数学题"
    echo "  ifeval         - IFEval 指令遵循"
    echo "  mmlu_pro       - MMLU-Pro 多领域知识"
    echo "  live_code_bench - LiveCodeBench 代码评测"
    echo ""
    echo "示例："
    echo "  bash run_evalscope.sh gpqa_diamond"
    echo "  bash run_evalscope.sh gsm8k math_500"
    echo "  bash run_evalscope.sh all"
}

# 检查是否需要显示帮助
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

# 检查 vLLM 服务是否运行
echo "Checking vLLM service..."
if curl -s http://127.0.0.1:9527/v1/models > /dev/null 2>&1; then
    echo "✓ vLLM service detected at port 9527"
else
    echo "⚠ vLLM service not detected at port 9527"
    echo "Please start vLLM first:"
    echo "  vllm serve /gpfs/gcsp/models/MiniMax-M2.7 --port 9527 --served-model-name MiniMax-M2.7"
    read -p "Press Enter to continue after starting vLLM..."
fi

echo ""
echo "Starting evaluation..."
echo ""

# 运行 evalscope 评测
evalscope eval \
  --model MiniMax-M2.7 \
  --api-url http://127.0.0.1:9527/v1/chat/completions \
  --api-key "EMPTY" \
  --datasets $DATASETS \
  --eval-type openai_api \
  --eval-batch-size 32 \
  --generation-config '{"timeout": 3600, "stream": true}' \
  2>&1 | tee ./log/benchmark_evalscope_${DATASET_TAG}_${LOG_TIME}.log ./log/benchmark_evalscope_${DATASET_TAG}_latest.log

echo ""
echo "=============================================="
echo "Evaluation complete!"
echo "Log saved to: ./log/benchmark_evalscope_${DATASET_TAG}_latest.log"
echo "=============================================="