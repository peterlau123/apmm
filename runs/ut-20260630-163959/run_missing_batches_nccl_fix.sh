#!/bin/bash
# Multi-GPU Batch Execution Script with NCCL Fix
# Generated: 2026-07-07
# Updated: 2026-07-07 - NCCL wheel reinstall fix applied (removed LD_PRELOAD workaround)

set -e

# Configuration
VLLM_DIR="/gpfs/gcsp/M2.7_verify/vllm"
RUN_DIR="/gpfs/gcsp/M2.7_verify/unit_test/ut-20260630-163959"
CONTAINER_T27="m2.7_v0.13.0_torch2.7"
CONTAINER_T25="v0.13.0_torch2.5.1_compile"

# NCCL Fix: NCCL 2.21.5 wheel reinstalled in container
# No LD_PRELOAD needed - NCCL is permanently fixed
NCCL_VERSION="2.21.5"

# Function to run test in PyTorch 2.7 container
run_in_t27() {
    local test_node="$1"
    local batch_id="$2"
    
    docker exec $CONTAINER_T27 bash -c "
        cd $VLLM_DIR && \
        RAY_ADDRESS=auto pytest -n 2 '$test_node' \
            --tb=short -v \
            --json-report --json-report-file=$RUN_DIR/batches/$batch_id/batch_results.json
    "
}

# Function to run test in PyTorch 2.5.1 container with NCCL fix
# NCCL wheel reinstalled - no LD_PRELOAD needed
run_in_t25() {
    local test_node="$1"
    local batch_id="$2"
    
    docker exec $CONTAINER_T25 bash -c "
        cd $VLLM_DIR && \
        RAY_ADDRESS=auto pytest -n 2 '$test_node' \
            --tb=short -v \
            --json-report --json-report-file=$RUN_DIR/batches/$batch_id/batch_results.json
    "
}

# Main execution
echo "=== Multi-GPU Batch Execution with NCCL Fix ==="
echo "Container T27: $CONTAINER_T27 (PyTorch 2.7)"
echo "Container T25: $CONTAINER_T25 (PyTorch 2.5.1 + NCCL $NCCL_VERSION)"
echo "NCCL Fix: wheel reinstalled (no LD_PRELOAD needed)"
echo ""

# Read missing batches
BATCHES=$(cat $RUN_DIR/missing_batches_list.txt 2>/dev/null || cat $RUN_DIR/missing_batches_remediation.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('\\n'.join([b['batch_id'] for b in d['batches']]))")

for batch_id in $BATCHES; do
    echo "Processing batch: $batch_id"
    
    # Get distributed tests from batch config
    DIST_TESTS=$(python3 -c "
import json
c = json.load(open('$RUN_DIR/batches/$batch_id/batch_config.json'))
for t in c.get('distributed_tests', []):
    print(t['test_node'])
" 2>/dev/null)
    
    # Run distributed tests in PyTorch 2.7 container (for _symmetric_memory API)
    for test_node in $DIST_TESTS; do
        if [[ "$test_node" == *"test_async_tp"* ]]; then
            echo "  Running in T27 (requires _symmetric_memory): $test_node"
            run_in_t27 "$test_node" "$batch_id" || echo "  [WARN] Test failed"
        else
            echo "  Running in T25 (with NCCL fix): $test_node"
            run_in_t25 "$test_node" "$batch_id" || echo "  [WARN] Test failed"
        fi
    done
    
    echo "  Batch $batch_id completed"
    echo ""
done

echo "=== All batches processed ==="
echo "Results in: $RUN_DIR/batches/*/batch_results.json"