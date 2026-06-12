#!/bin/bash
# MiniMax-M2.7 SWE-bench 评测完整流程
# 按照官方文档：https://www.swebench.com/SWE-bench/guides/evaluation/

set -e

echo "================================================"
echo "SWE-bench Evaluation for MiniMax-M2.7"
echo "================================================"

# Step 1: 配置 Git 环境
echo ""
echo "Step 1: Configure Git environment"
source /gpfs/gcsp/M2.7_verify/tools/git/setup_git.sh

# Step 2: 启动 vLLM 服务（提醒）
echo ""
echo "Step 2: Start vLLM service (if not running)"
echo "Please ensure vLLM is running in another terminal:"
echo ""
echo "  vllm serve /gpfs/gcsp/models/MiniMax-M2.7 \\"
echo "      --host 0.0.0.0 \\"
echo "      --port 8000 \\"
echo "      --served-model-name MiniMax-M2.7 \\"
echo "      --max-model-len 4096"
echo ""

# Check if vLLM is running
if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo "✓ vLLM service detected"
else
    echo "⚠ vLLM service not detected. Please start it before continuing."
    read -p "Press Enter to continue after starting vLLM..."
fi

# Step 3: 生成 predictions
echo ""
echo "Step 3: Generate predictions"
python /gpfs/gcsp/M2.7_verify/accuracy_test/inference_with_vllm.py \
    --dataset_path /gpfs/gcsp/M2.7_verify/accuracy_test/swe-bench_multilingual_with_text \
    --output_file /gpfs/gcsp/M2.7_verify/accuracy_test/predictions_minimax.jsonl \
    --api_base http://localhost:8000/v1 \
    --model_name MiniMax-M2.7 \
    --temperature 0.2 \
    --max_tokens 2048

# Step 4: 评估 predictions（使用官方 harness）
echo ""
echo "Step 4: Evaluate predictions using official harness"
echo "This will use Docker to validate patches"
echo ""

python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Multilingual \
    --predictions_path /gpfs/gcsp/M2.7_verify/accuracy_test/predictions_minimax.jsonl \
    --max_workers 4 \
    --run_id minimax_m2.7_multilingual

# Step 5: 查看结果
echo ""
echo "Step 5: View evaluation results"
echo ""
echo "Results directory: evaluation_results/minimax_m2.7_multilingual/"
echo ""
echo "Key metrics:"
echo "  - results.json: Overall resolution rate"
echo "  - instance_results.jsonl: Detailed results per instance"
echo ""

ls -lh evaluation_results/minimax_m2.7_multilingual/ 2>/dev/null || echo "Results will be available after evaluation completes"

echo ""
echo "================================================"
echo "Evaluation complete!"
echo "================================================"