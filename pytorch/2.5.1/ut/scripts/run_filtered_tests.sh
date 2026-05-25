#!/bin/bash
# run_filtered_tests.sh - 运行过滤后的测试并记录结果
# 用法:
#   ./run_filtered_tests.sh                              # 运行所有测试，输出到脚本同目录
#   ./run_filtered_tests.sh --test                       # 运行10个测试（验证输出格式）
#   ./run_filtered_tests.sh --limit 5                    # 运行5个测试
#   ./run_filtered_tests.sh --tests-dir /path/to/tests   # 指定 tests 目录
#   ./run_filtered_tests.sh --output-dir /path/to/output # 指定输出目录
#   ./run_filtered_tests.sh --parallel 8                 # 指定并行数（默认16）
#   ./run_filtered_tests.sh --serial                     # 强制串行模式（不使用并行）
#   ./run_filtered_tests.sh --timeout 300                # 单测试超时秒数（默认300）
#   ./run_filtered_tests.sh --tests-dir /vllm/tests --output-dir /results --test  # 组合使用

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 配置
PARALLEL_JOBS=16
TEST_MODE=false
TEST_LIMIT=0
TESTS_DIR=""
OUTPUT_DIR=""
FORCE_SERIAL=false
TEST_TIMEOUT=300

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            TEST_MODE=true
            TEST_LIMIT=10
            shift
            ;;
        --limit)
            TEST_MODE=true
            TEST_LIMIT="$2"
            shift 2
            ;;
        --tests-dir)
            TESTS_DIR="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --serial)
            FORCE_SERIAL=true
            shift
            ;;
        --timeout)
            TEST_TIMEOUT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --test              Run 10 tests (for verifying output format)"
            echo "  --limit N           Run N tests"
            echo "  --tests-dir DIR     Specify tests directory (default: auto-detect)"
            echo "  --output-dir DIR    Specify output directory (default: SCRIPT_DIR/test_results)"
            echo "  --parallel N        Number of parallel jobs (default: 16)"
            echo "  --serial            Force serial mode (no parallel execution)"
            echo "  --timeout N         Timeout per test in seconds (default: 300)"
            echo "  --help              Show this help message"
            echo ""
            echo "Execution modes:"
            echo "  - GNU parallel (preferred, fastest)"
            echo "  - xargs -P (fallback, available on most systems)"
            echo "  - Serial (fallback, no parallel support)"
            echo ""
            echo "After tests finish, parse_results.py generates the final report."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

set -o pipefail

# 自动检测 tests 目录（如果未指定）
detect_tests_dir() {
    if [ -n "${TESTS_DIR}" ]; then
        return
    fi

    if [ -d "tests" ]; then
        TESTS_DIR="tests"
    elif [ -d "vllm/tests" ]; then
        TESTS_DIR="vllm/tests"
    elif [ -d "/gpfs/gcsp/M2.7_verify/vllm/tests" ]; then
        TESTS_DIR="/gpfs/gcsp/M2.7_verify/vllm/tests"
    else
        echo "ERROR: Could not find tests directory."
        echo "Please specify with --tests-dir option"
        exit 1
    fi
}

# 设置输出目录
setup_output_dir() {
    if [ -z "${OUTPUT_DIR}" ]; then
        OUTPUT_DIR="${SCRIPT_DIR}/test_results"
    fi

    RESULTS_DIR="${OUTPUT_DIR}"
    PASSED_LOG="${RESULTS_DIR}/passed.log"
    SUMMARY_JSON="${RESULTS_DIR}/summary.json"
    TEST_LIST_FILE="${RESULTS_DIR}/test_list.txt"
    OUTPUTS_DIR="${RESULTS_DIR}/outputs"

    mkdir -p "${RESULTS_DIR}"
    mkdir -p "${OUTPUTS_DIR}"
}

# 初始化文件
init_files() {
    printf '' > "${PASSED_LOG}"
    cat > "${SUMMARY_JSON}" << EOF
{
    "start_time": "",
    "end_time": "",
    "total_tests": 0,
    "passed": 0,
    "failed": 0,
    "errors": 0,
    "test_mode": ${TEST_MODE},
    "test_limit": ${TEST_LIMIT},
    "parallel_jobs": ${PARALLEL_JOBS},
    "tests_dir": "${TESTS_DIR}",
    "output_dir": "${OUTPUT_DIR}"
}
EOF
}

# 收集测试列表
collect_tests() {
    echo "Tests directory: ${TESTS_DIR}"
    echo "Collecting tests..."

    pytest "${TESTS_DIR}" --collect-only \
        --ignore-glob="${TESTS_DIR}/**/rocm*" \
        --ignore-glob="${TESTS_DIR}/**/tpu*" \
        --ignore-glob="${TESTS_DIR}/**/multimodal*" \
        --ignore-glob="${TESTS_DIR}/**/nixl*" \
        --ignore-glob="${TESTS_DIR}/**/ec_connector*" \
        --ignore-glob="${TESTS_DIR}/**/*image*.py" \
        --ignore-glob="${TESTS_DIR}/**/*video*.py" \
        --ignore-glob="${TESTS_DIR}/**/*audio*" \
        --ignore-glob="${TESTS_DIR}/**/encoder*" \
        --ignore-glob="${TESTS_DIR}/**/prithvi*" \
        --ignore-glob="${TESTS_DIR}/models/language/generation/test_gemma.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation/test_granite.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation/test_hybrid.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation/test_mistral.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation/test_phimoe.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation_ppl_test/test_gemma.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation_ppl_test/test_gpt.py" \
        --ignore-glob="${TESTS_DIR}/models/language/generation_ppl_test/test_qwen.py" \
        --ignore-glob="${TESTS_DIR}/models/language/pooling_mteb_test/*" \
        --ignore-glob="${TESTS_DIR}/models/language/pooling/*" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_deepseekr1_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_deepseekv3_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_ernie45_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_glm4_moe_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_gptoss_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_granite_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_holo2_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_hunyuan_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_mistral_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_olmo3_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_qwen3_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_seedoss_reasoning_parser.py" \
        --ignore-glob="${TESTS_DIR}/reasoning/test_base_thinking_reasoning_parser.py" \
        -q 2>&1 | grep -E "^${TESTS_DIR}/" | sed 's/^[[:space:]]*//' > "${TEST_LIST_FILE}"

    TOTAL_TESTS=$(wc -l < "${TEST_LIST_FILE}")

    if [ "${TEST_MODE}" = true ]; then
        head -n "${TEST_LIMIT}" "${TEST_LIST_FILE}" > "${TEST_LIST_FILE}.tmp"
        mv "${TEST_LIST_FILE}.tmp" "${TEST_LIST_FILE}"
        ACTUAL_TESTS=$(wc -l < "${TEST_LIST_FILE}")
        echo "TEST MODE: Running ${ACTUAL_TESTS} tests (limited from ${TOTAL_TESTS})"
        TOTAL_TESTS=${ACTUAL_TESTS}
    else
        echo "Found ${TOTAL_TESTS} tests to run"
    fi

    python3 -c "
import json
from datetime import datetime
with open('${SUMMARY_JSON}', 'r') as f:
    data = json.load(f)
data['total_tests'] = ${TOTAL_TESTS}
data['start_time'] = datetime.now().isoformat()
with open('${SUMMARY_JSON}', 'w') as f:
    json.dump(data, f, indent=2)
"
}

# 运行单个测试 —— 只保存原始输出，不做任何提取
run_single_test() {
    local test_name="$1"
    local safe_name=$(echo "$test_name" | sed 's/[:/]/_/g' | sed 's/\.\//_/g')
    local output_file="${OUTPUTS_DIR}/${safe_name}.log"
    local exit_code_file="${OUTPUTS_DIR}/${safe_name}.exit_code"

    echo ">>> Running: ${test_name}"

    timeout "${TEST_TIMEOUT}" pytest "${test_name}" -v --tb=long 2>&1 | tee "${output_file}"
    local exit_code=${PIPESTATUS[0]}

    # 将 exit code 写入文件供后续 parse_results.py 读取
    # exit_code: 0=passed, 1=failed, 2+enderror, 124=timeout
    echo "${exit_code}" > "${exit_code_file}"

    if [ ${exit_code} -eq 0 ]; then
        echo "${test_name}" >> "${PASSED_LOG}"
        echo "<<< PASSED: ${test_name}"
        rm -f "${output_file}" "${exit_code_file}"
    else
        echo "<<< NOT PASSED: ${test_name} (exit_code=${exit_code})"
    fi
}

# 导出函数和变量
export -f run_single_test
export RESULTS_DIR OUTPUTS_DIR PASSED_LOG TEST_TIMEOUT

# 更新统计（简化版，只算 passed；failed/errors 由 parse_results.py 计算）
update_summary() {
    local passed=$(wc -l < "${PASSED_LOG}")

    python3 -c "
import json
from datetime import datetime
with open('${SUMMARY_JSON}', 'r') as f:
    data = json.load(f)
data['passed'] = ${passed}
data['end_time'] = datetime.now().isoformat()
with open('${SUMMARY_JSON}', 'w') as f:
    json.dump(data, f, indent=2)
"
}

# 运行测试（选择执行模式）
run_tests() {
    # 检测执行模式
    if [ "${FORCE_SERIAL}" = true ]; then
        EXEC_MODE="serial"
    elif command -v parallel &> /dev/null; then
        EXEC_MODE="gnu_parallel"
    elif command -v xargs &> /dev/null && xargs --version 2>&1 | grep -q "GNU"; then
        EXEC_MODE="xargs"
    else
        EXEC_MODE="serial"
    fi

    echo "Execution mode: ${EXEC_MODE}"
    echo "Parallel jobs: ${PARALLEL_JOBS}"
    echo ""

    case "${EXEC_MODE}" in
        gnu_parallel)
            cat "${TEST_LIST_FILE}" | parallel -j "${PARALLEL_JOBS}" --lb run_single_test {}
            ;;
        xargs)
            cat "${TEST_LIST_FILE}" | xargs -P "${PARALLEL_JOBS}" -d '\n' -I {} bash -c 'run_single_test "{}"'
            ;;
        serial)
            echo "Running tests serially (no parallel support available)"
            local count=0
            while IFS= read -r test_name; do
                if [ -n "${test_name}" ]; then
                    run_single_test "${test_name}"
                    count=$((count + 1))
                    echo "Progress: ${count}/${TOTAL_TESTS}"
                fi
            done < "${TEST_LIST_FILE}"
            ;;
    esac
}

# 主流程
main() {
    echo "=============================================="
    echo "vLLM Filtered Test Runner"
    if [ "${TEST_MODE}" = true ]; then
        echo "MODE: TEST (running ${TEST_LIMIT} tests)"
    else
        echo "MODE: FULL (running all tests)"
    fi
    echo "=============================================="

    detect_tests_dir
    setup_output_dir

    echo "Tests dir:    ${TESTS_DIR}"
    echo "Output dir:   ${OUTPUT_DIR}"
    echo "=============================================="

    init_files
    collect_tests

    echo ""
    echo "Running tests..."
    echo "=============================================="

    run_tests

    echo "=============================================="
    update_summary

    # 调用 parse_results.py 解析所有 .log 并生成最终报告
    echo ""
    echo "Parsing results with parse_results.py..."
    python3 "${SCRIPT_DIR}/parse_results.py" --outputs-dir "${OUTPUTS_DIR}" --results-dir "${RESULTS_DIR}" --tests-dir "${TESTS_DIR}"

    echo ""
    echo "Test run completed!"
    echo "Results saved to: ${RESULTS_DIR}"
    echo "Key files for third-party analysis:"
    echo "  - ${RESULTS_DIR}/error_report.json  (structured error catalog with classification)"
    echo "  - ${RESULTS_DIR}/summary.json"
    echo "  - ${RESULTS_DIR}/outputs/           (raw pytest logs per test)"
}

main
