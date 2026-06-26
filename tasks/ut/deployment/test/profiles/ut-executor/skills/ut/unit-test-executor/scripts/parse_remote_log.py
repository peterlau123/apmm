#!/usr/bin/env python3
"""
parse_remote_log.py - 解析远程 grep 输出，生成 batch_results.json

用法：
    python parse_remote_log.py --log-file PATH --batch-id ID --output PATH
    python parse_remote_log.py --stdin --batch-id ID --output PATH

从远程 ut_logs grep 输出的格式：
    tests/test_config.py::test_load PASSED
    tests/test_model.py::test_init FAILED - AssertionError: ...
    tests/distributed/test_pp.py::test_pipeline ERROR - ImportError: ...

输出 batch_results.json 符合 batch_results_schema.json 格式。
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Error Categorization (from batch_test_runner.py) ─────────────────────────────

# C/E/D/P/M/S 分类框架关键字
ERROR_PATTERNS = {
    "M": ["LocalEntryNotFoundError", "config.json", "model not found", "HuggingFace"],
    "D": ["ImportError", "ModuleNotFoundError", "cannot import", "undefined symbol"],
    "P": ["wrap_triton", "torch.compile", "VllmBackend", "CompilationError"],
    "E": ["CUDA out of memory", "OSError", "Network", "timeout", "Connection"],
    "S": ["pytest.skip", "SkipTest", "Skipped", "not supported"],
}

# C/E/D/P/M/S → batch_results error_type 映射
ERROR_TYPE_MAP = {
    "C": "functional",     # Code Bug
    "E": "other",          # Environment
    "D": "dependency",     # Dependency
    "P": "resource",       # Platform
    "M": "download_error", # Model
    "S": None,             # Skip (不计入 batch_results)
}


def categorize_error_code(error_detail: str) -> str:
    """
    Categorize error into C/E/D/P/M/S code.

    Args:
        error_detail: Error message or traceback

    Returns:
        Category code (C, E, D, P, M, S)
    """
    for code, keywords in ERROR_PATTERNS.items():
        for keyword in keywords:
            if keyword.lower() in error_detail.lower():
                return code
    return "C"  # Default to Code Bug


def map_error_type(code: str) -> Optional[str]:
    """
    Map C/E/D/P/M/S code to batch_results error_type enum.

    Args:
        code: Category code (C, E, D, P, M, S)

    Returns:
        batch_results error_type or None for Skip
    """
    return ERROR_TYPE_MAP.get(code, "other")


def extract_error_message(error_detail: str, max_len: int = 500) -> Optional[str]:
    """
    Extract key error message from pytest error detail.

    Args:
        error_detail: Error message after PASSED/FAILED/ERROR
        max_len: Maximum length to truncate

    Returns:
        Truncated error message or None
    """
    if not error_detail:
        return None

    # Look for common error patterns
    patterns = [
        r"AssertionError: (.+)",
        r"ImportError: (.+)",
        r"ModuleNotFoundError: (.+)",
        r"RuntimeError: (.+)",
        r"TypeError: (.+)",
        r"ValueError: (.+)",
        r"CUDA out of memory.*",
        r"LocalEntryNotFoundError.*",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_detail, re.IGNORECASE | re.MULTILINE)
        if match:
            msg = match.group(0)
            return msg[:max_len] if len(msg) > max_len else msg

    # Fallback: use the whole detail
    return error_detail[:max_len] if len(error_detail) > max_len else error_detail


# ── Log Parsing ──────────────────────────────────────────────────────────────────

def parse_grep_output(log_content: str) -> dict:
    """
    Parse pytest -v output to extract test results.

    Input format (pytest -v actual output):
        tests/test_config.py::test_load PASSED [  5%]
        tests/test_model.py::test_init FAILED [ 10%]
        tests/distributed/test_pp.py::test_pipeline ERROR [ 15%]

    Args:
        log_content: Raw pytest output string

    Returns:
        Dictionary with test results list
    """
    results = {
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "total": 0,
        "test_results": [],
    }

    # Pattern for pytest -v output (actual format from test logs)
    # Format: test_node + PASSED/FAILED/ERROR + [ percentage%]
    test_pattern = re.compile(
        r"(tests/[^\s]+)\s+(PASSED|FAILED|ERROR|SKIPPED)\s+\[\s*\d+%\]",
        re.MULTILINE
    )

    for match in test_pattern.finditer(log_content):
        test_node = match.group(1)
        status = match.group(2)
        # Error detail extracted from ERRORS/FAILURES section separately
        add_test_result(results, test_node, status, None)

    results["total"] = results["passed"] + results["failed"] + \
                        results["error"] + results["skipped"]

    return results


def add_test_result(results: dict, test_node: str, status: str, error_detail: Optional[str]):
    """Add a single test result to results dict."""
    status_lower = status.lower()

    # Categorize error for failed/error tests
    error_type = None
    error_message = None
    error_code = None

    if status_lower in ("failed", "error"):
        error_code = categorize_error_code(error_detail or "")
        error_type = map_error_type(error_code)
        error_message = extract_error_message(error_detail or "")

    test_entry = {
        "test_node": test_node,
        "status": status_lower,
        "error_type": error_type,
        "error_message": error_message,
        "duration_ms": None,  # Not available from grep output
        "exit_code": None,    # Not available from grep output
    }

    results["test_results"].append(test_entry)

    if status_lower == "passed":
        results["passed"] += 1
    elif status_lower == "failed":
        results["failed"] += 1
    elif status_lower == "error":
        results["error"] += 1
    elif status_lower == "skipped":
        results["skipped"] += 1


# ── batch_results.json Generation ────────────────────────────────────────────────

def generate_batch_results(
    parsed: dict,
    batch_id: str,
    log_file: Optional[str] = None
) -> dict:
    """
    Generate batch_results.json conforming to batch_results_schema.json.

    Args:
        parsed: Parsed results from parse_grep_output()
        batch_id: Batch identifier (e.g., "batch_20260611_001")
        log_file: Optional log file path

    Returns:
        batch_results dictionary
    """
    return {
        "batch_id": batch_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "tests": parsed["test_results"],
        "stats": {
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "error": parsed["error"],
            "total": parsed["total"],
        },
        "log_file": log_file,
    }


# ── CLI Entry ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="解析远程 grep 输出，生成 batch_results.json"
    )
    parser.add_argument(
        "--log-file", "-f",
        help="日志文件路径 (本地文件)"
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="从 stdin 读取日志内容"
    )
    parser.add_argument(
        "--batch-id", "-b",
        required=True,
        help="批次 ID (e.g., batch_20260611_001)"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="输出文件路径 (batch_results.json)"
    )
    parser.add_argument(
        "--remote-log",
        help="远程日志路径 (用于记录在 log_file 字段)"
    )

    args = parser.parse_args()

    # Read log content
    if args.stdin:
        log_content = sys.stdin.read()
    elif args.log_file:
        log_content = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    else:
        print("[ERROR] 必须指定 --log-file 或 --stdin", file=sys.stderr)
        sys.exit(1)

    # Parse
    parsed = parse_grep_output(log_content)

    if parsed["total"] == 0:
        print("[WARNING] 未解析到任何测试结果", file=sys.stderr)

    # Generate batch_results
    batch_results = generate_batch_results(
        parsed,
        batch_id=args.batch_id,
        log_file=args.remote_log
    )

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(batch_results, f, indent=2, ensure_ascii=False)

    print(f"[OK] 输出: {output_path}")
    print(f"     通过: {parsed['passed']}, 失败: {parsed['failed']}, 错误: {parsed['error']}, 跳过: {parsed['skipped']}")


if __name__ == "__main__":
    main()