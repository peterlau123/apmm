#!/bin/bash
# convert_to_markdown.sh - 将 JSON 测试结果转换为 Markdown 报告
# 用法:
#   ./convert_to_markdown.sh                      # 默认输出到脚本同目录的 test_results
#   ./convert_to_markdown.sh --output-dir /path   # 指定输出目录
#   ./convert_to_markdown.sh --help               # 显示帮助

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/test_results"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --output-dir)
            RESULTS_DIR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --output-dir DIR    Specify output directory (default: SCRIPT_DIR/test_results)"
            echo "  --help              Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

SUMMARY_JSON="${RESULTS_DIR}/summary.json"
PASSED_LOG="${RESULTS_DIR}/passed.log"
FAILED_JSON="${RESULTS_DIR}/failed.json"
ERRORS_JSON="${RESULTS_DIR}/errors.json"
OUTPUT_DIR="${RESULTS_DIR}/outputs"
REPORT_MD="${RESULTS_DIR}/report.md"

# 检查文件是否存在
if [ ! -f "${SUMMARY_JSON}" ]; then
    echo "ERROR: summary.json not found in ${RESULTS_DIR}"
    echo "Please run run_filtered_tests.sh first"
    exit 1
fi

python3 << 'PYTHON_SCRIPT'
import json
import os
from datetime import datetime

# 读取数据
try:
    with open('${SUMMARY_JSON}', 'r') as f:
        summary = json.load(f)
except Exception as e:
    print(f"Error reading summary.json: {e}")
    exit(1)

try:
    with open('${PASSED_LOG}', 'r') as f:
        passed_tests = [line.strip() for line in f if line.strip()]
except:
    passed_tests = []

try:
    with open('${FAILED_JSON}', 'r') as f:
        failed_data = json.load(f)
        failed_tests = failed_data['tests']
except:
    failed_tests = []

try:
    with open('${ERRORS_JSON}', 'r') as f:
        errors_data = json.load(f)
        error_tests = errors_data['tests']
except:
    error_tests = []

# 计算耗时
def calculate_duration(start, end):
    if not start or not end:
        return "N/A"
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        duration = end_dt - start_dt
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
    except:
        return "N/A"

duration = calculate_duration(summary.get('start_time', ''), summary.get('end_time', ''))

# 读取完整输出文件
def read_output_file(filepath, max_lines=100):
    if not filepath or not os.path.exists(filepath):
        return "Output file not available"
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            if len(lines) > max_lines:
                return ''.join(lines[:max_lines]) + f"\n... (truncated, total {len(lines)} lines)"
            return ''.join(lines)
    except Exception as e:
        return f"Error reading file: {e}"

# 生成 Markdown 报告
report = f"""# vLLM Unit Test Report

## Summary

| Metric | Value |
|--------|-------|
| **Total Tests** | {summary.get('total_tests', 0)} |
| **Passed** | {summary.get('passed', 0)} |
| **Failed** | {summary.get('failed', 0)} |
| **Errors** | {summary.get('errors', 0)} |
| **Pass Rate** | {summary.get('passed', 0) / max(summary.get('total_tests', 1), 1) * 100:.1f}% |
| **Duration** | {duration} |
| **Start Time** | {summary.get('start_time', 'N/A')} |
| **End Time** | {summary.get('end_time', 'N/A')} |
| **Test Mode** | {summary.get('test_mode', False)} |
| **Tests Dir** | {summary.get('tests_dir', 'N/A')} |
| **Output Dir** | {summary.get('output_dir', 'N/A')} |

---

## Errors ({len(error_tests)})

Errors indicate import failures or collection errors, typically due to missing dependencies or incompatible PyTorch versions.

"""

# 错误测试
if error_tests:
    for test in error_tests:
        error_type = test.get('error_type', 'Unknown')
        error_msg = test.get('error_message', '')
        output_file = test.get('output_file', '')
        full_output = read_output_file('${OUTPUT_DIR}/' + os.path.basename(output_file), max_lines=50)

        report += f"""### {test['test_file']}

**Error Type**: `{error_type}`

**Error Message**: `{error_msg}`

**Timestamp**: {test.get('timestamp', 'N/A')}

<details>
<summary>Output (click to expand)</summary>

```
{full_output}
```

</details>

"""
else:
    report += "✅ No errors found.\n\n"

report += f"""---

## Failed Tests ({len(failed_tests)})

"""

# 失败测试
if failed_tests:
    for test in failed_tests:
        failure_reason = test.get('failure_reason', ['Unknown'])
        output_file = test.get('output_file', '')
        full_output = read_output_file('${OUTPUT_DIR}/' + os.path.basename(output_file), max_lines=80)

        # 格式化失败原因
        failure_str = '\n'.join([f"- `{r}`" for r in failure_reason[:3]])

        report += f"""### {test['test_file']}

**Failure Reason**:
{failure_str}

**Timestamp**: {test.get('timestamp', 'N/A')}

<details>
<summary>Output (click to expand)</summary>

```
{full_output}
```

</details>

"""
else:
    report += "✅ No failed tests.\n\n"

report += f"""---

## Passed Tests ({len(passed_tests)})

"""

if passed_tests:
    # 按文件名分组
    grouped = {}
    for test in passed_tests:
        file_path = test.split('::')[0] if '::' in test else test
        if file_path not in grouped:
            grouped[file_path] = []
        grouped[file_path].append(test)

    report += "<details>\n<summary>Click to expand passed tests list ({len(passed_tests)} tests)</summary>\n\n"
    for file_path, tests in sorted(grouped.items()):
        report += f"#### {file_path} ({len(tests)} tests)\n"
        for test in tests:
            test_func = test.split('::')[-1] if '::' in test else test
            report += f"- ✅ `{test_func}`\n"
        report += "\n"
    report += "</details>\n"
else:
    report += "❌ No passed tests.\n"

# 添加附录
report += f"""
---

## Appendix

### Filter Command Used

```bash
pytest <tests_dir> --collect-only \
    --ignore-glob="<tests_dir>/**/rocm*" \
    --ignore-glob="<tests_dir>/**/tpu*" \
    --ignore-glob="<tests_dir>/**/multimodal*" \
    --ignore-glob="<tests_dir>/**/nixl*" \
    --ignore-glob="<tests_dir>/**/ec_connector*" \
    --ignore-glob="<tests_dir>/**/*image*.py" \
    --ignore-glob="<tests_dir>/**/*video*.py" \
    --ignore-glob="<tests_dir>/**/*audio*" \
    --ignore-glob="<tests_dir>/**/encoder*" \
    --ignore-glob="<tests_dir>/**/prithvi*" \
    --ignore-glob="<tests_dir>/models/language/generation/test_gemma.py" \
    --ignore-glob="<tests_dir>/models/language/generation/test_granite.py" \
    --ignore-glob="<tests_dir>/models/language/generation/test_hybrid.py" \
    --ignore-glob="<tests_dir>/models/language/generation/test_mistral.py" \
    --ignore-glob="<tests_dir>/models/language/generation/test_phimoe.py" \
    --ignore-glob="<tests_dir>/models/language/generation_ppl_test/test_gemma.py" \
    --ignore-glob="<tests_dir>/models/language/generation_ppl_test/test_gpt.py" \
    --ignore-glob="<tests_dir>/models/language/generation_ppl_test/test_qwen.py" \
    --ignore-glob="<tests_dir>/models/language/pooling_mteb_test/*" \
    --ignore-glob="<tests_dir>/models/language/pooling/*" \
    --ignore-glob="<tests_dir>/reasoning/test_deepseekr1_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_deepseekv3_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_ernie45_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_glm4_moe_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_gptoss_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_granite_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_holo2_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_hunyuan_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_mistral_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_olmo3_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_qwen3_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_seedoss_reasoning_parser.py" \
    --ignore-glob="<tests_dir>/reasoning/test_base_thinking_reasoning_parser.py" \
    -v
```

### Output Files

Failed/Error test outputs are stored in: `${RESULTS_DIR}/outputs/`

- Error outputs: {len(error_tests)} files
- Failed outputs: {len(failed_tests)} files
- Passed tests: outputs deleted (no issues)

---

*Report generated at {datetime.now().isoformat()}*
"""

# 写入文件
try:
    with open('${REPORT_MD}', 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Markdown report saved to: ${REPORT_MD}")
    print(f"Report size: {len(report)} characters")
except Exception as e:
    print(f"Error writing report: {e}")
    exit(1)
PYTHON_SCRIPT