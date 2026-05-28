#!/bin/bash
set -euo pipefail

# MiniMax-M2.7 vLLM Benchmark Script for B300
# Parameters: ISL=64K, OSL=2K, max_concurrency=4~64

IMAGE="nvcr.io/nvidia/tritonserver:26.04-vllm-python-py3"
CONTAINER_NAME="vllm_m27_bench"
PORT=8888
MODEL_PATH="/data/models/models--MiniMaxAI--MiniMax-M2.7/snapshots/9c327df40295b7e48890da17d07c785119454421"
BENCH_PATH="/ix"
LOG_FILE="${BENCH_PATH}/vllm_m27_server.log"

# Benchmark parameters
ISL=65536    # 64K input tokens
OSL=2048     # 2K output tokens
TP=4         # Tensor Parallelism (use GPUs 0-3)
GPU_DEVICES="0,1,2,3"

# Concurrency range
CONC_LIST="4 8 16 32 64"

# Number of prompts (should be 10x of max concurrency for good statistics)
NUM_PROMPTS=640

# Stop any existing container
sudo docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "=========================================="
echo "MiniMax-M2.7 vLLM Benchmark"
echo "=========================================="
echo "Model: MiniMax-M2.7"
echo "ISL: ${ISL} (64K)"
echo "OSL: ${OSL} (2K)"
echo "TP: ${TP}"
echo "GPUs: ${GPU_DEVICES}"
echo "Concurrency: ${CONC_LIST}"
echo "=========================================="

# Start vLLM server
echo "Starting vLLM server..."
sudo docker run -d --name "$CONTAINER_NAME" \
    --gpus '"device=${GPU_DEVICES}"' \
    --network host \
    --ipc host \
    --ulimit memlock=-1:-1 \
    --ulimit stack=67108864:67108864 \
    -v ~/models:/data/models \
    -v ~/bench/InferenceX:${BENCH_PATH} \
    "$IMAGE" \
    vllm serve "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port $PORT \
    --trust-remote-code \
    --tensor-parallel-size $TP \
    --max-model-len 131072 \
    --max-num-batched-tokens 131072 \
    --gpu-memory-utilization 0.90 \
    --disable-log-requests

echo "Server container started. Waiting for readiness..."

# Wait for server to be ready
MAX_WAIT=600
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -s http://localhost:$PORT/v1/models >/dev/null 2>&1; then
        echo "Server is ready!"
        break
    fi
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    echo "Waiting... ($ELAPSED/$MAX_WAIT seconds)"
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "ERROR: Server did not become ready within $MAX_WAIT seconds"
    sudo docker logs "$CONTAINER_NAME" | tail -100
    exit 1
fi

echo "Server is ready. Starting benchmarks..."

# Run benchmark for each concurrency level
RESULTS_DIR="${BENCH_PATH}/results/m27_vllm_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

for CONC in $CONC_LIST; do
    echo ""
    echo "=========================================="
    echo "Running benchmark with concurrency=$CONC"
    echo "=========================================="

    RESULT_FILE="m27_${ISL}_${OSL}_vllm_tp${TP}_conc${CONC}_b300.json"

    python3 ${BENCH_PATH}/utils/bench_serving/benchmark_serving.py \
        --model "$MODEL_PATH" \
        --backend vllm \
        --base-url http://0.0.0.0:$PORT \
        --dataset-name random \
        --random-input-len $ISL \
        --random-output-len $OSL \
        --random-range-ratio 0.8 \
        --num-prompts $NUM_PROMPTS \
        --max-concurrency $CONC \
        --request-rate inf \
        --ignore-eos \
        --save-result \
        --num-warmups 64 \
        --percentile-metrics ttft,tpot,itl,e2el \
        --result-dir "$RESULTS_DIR" \
        --result-filename "$RESULT_FILE" \
        --use-chat-template

    echo "Benchmark concurrency=$CONC completed!"
    echo "Result saved to: $RESULTS_DIR/$RESULT_FILE"
done

echo ""
echo "=========================================="
echo "All benchmarks completed!"
echo "=========================================="
echo "Results saved in: $RESULTS_DIR"
ls -la "$RESULTS_DIR"

# Stop container
echo "Stopping vLLM server..."
sudo docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "Done!"