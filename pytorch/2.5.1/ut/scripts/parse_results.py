#!/usr/bin/env python3
"""
parse_results.py - 解析 pytest 输出日志，提取结构化错误信息并分类

产出 error_report.json，包含:
  - 每个失败/错误测试的详细信息
  - 按 exception_type 分类的统计
  - torch 相关标记
  - 每类错误的一个典型样例

用法:
  python3 parse_results.py --outputs-dir /path/to/outputs --results-dir /path/to/results --tests-dir /path/to/tests
"""

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime


# ========== pytest 输出解析器 ==========

def parse_pytest_log(log_text: str, exit_code: int, test_name: str) -> dict:
    """从 pytest --tb=long 的输出中提取结构化错误信息"""
    result = {
        "test_file": test_name,
        "exit_code": exit_code,
        "status": "unknown",
        "exception_type": "",
        "exception_message": "",
        "failure_location": "",
        "traceback_summary": [],
        "captured_output": "",
        "torch_related": False,
        "torch_evidence": [],
        "duration_seconds": 0.0,
        "pytest_summary_line": "",
    }

    # 1. 确定状态
    # pytest exit code: 0=passed, 1=failed(assertion), 2+enderror/interrupt, 124=timeout
    if exit_code == 124:
        result["status"] = "timeout"
        result["exception_type"] = "TimeoutError"
        result["exception_message"] = f"Test timed out"
        return result
    elif exit_code == 0:
        result["status"] = "passed"
        return result
    elif exit_code == 1:
        result["status"] = "failed"
    elif exit_code >= 2:
        result["status"] = "error"
    else:
        result["status"] = "unknown"

    # 2. 提取 pytest summary 行: "FAILED xxx - ExceptionType" 或 "ERROR xxx"
    summary_match = re.search(
        r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.+))?$",
        log_text, re.MULTILINE
    )
    if summary_match:
        result["pytest_summary_line"] = summary_match.group(0).strip()
        if summary_match.group(3):
            # summary 中的 exception type (如 "AssertionError", "RuntimeError")
            result["exception_type"] = summary_match.group(3).strip()

    # 3. 提取异常详情: 从 "E   XXXError: message" 行
    # pytest --tb=long 格式: "E   ExceptionType: message"
    e_lines = []
    for line in log_text.splitlines():
        if re.match(r"^E\s+", line):
            e_lines.append(line[2:].strip())  # 去掉 "E   " 前缀

    if e_lines:
        # 最后一行 E 通常是最终异常
        last_e = e_lines[-1]
        exc_match = re.match(
            r"([A-Za-z]+Error|[A-Za-z]+Exception|RuntimeError|ValueError|TypeError"
            r"|KeyError|ImportError|OSError|TimeoutError|StopIteration"
            r"|NotImplementedError|AttributeError|NameError|IndexError"
            r"|FileNotFoundError|ModuleNotFoundError|UnboundLocalError"
            r"|OverflowError|ZeroDivisionError|RecursionError"
            r"|MemoryError|BufferError|ArithmeticError"
            r"|LookupError|SyntaxError|SystemError|SystemExit): (.+)$",
            last_e
        )
        if exc_match:
            if not result["exception_type"] or result["exception_type"] == "":
                result["exception_type"] = exc_match.group(1)
            result["exception_message"] = exc_match.group(2)
        else:
            # E 行不是标准 ExceptionType: msg 格式（如 assertion 表达式）
            if not result["exception_type"] or result["exception_type"] == "":
                # 尝试从 E 行推断
                for e in e_lines:
                    m = re.match(r"([A-Za-z]+Error):", e)
                    if m:
                        result["exception_type"] = m.group(1)
                        break
            result["exception_message"] = last_e[:500]

    # 4. 提取失败位置: "test_file.py:NN: ExceptionType"
    location_match = re.search(
        r"^(\S+\.py:\d+):\s*(\w+Error|\w+Exception|RuntimeError|ValueError|TypeError)",
        log_text, re.MULTILINE
    )
    if location_match:
        result["failure_location"] = location_match.group(1)

    # 5. 提取 traceback 概要: 文件路径行
    # pytest --tb=long 的 traceback 行格式:
    #   /path/to/file.py:NN: in function_name
    tb_lines = []
    for line in log_text.splitlines():
        if re.match(r"^(?:/|\.)[^\s]+\.py:\d+", line):
            tb_lines.append(line.strip())
    # 只取最后 10 行（最靠近异常点的调用栈）
    result["traceback_summary"] = tb_lines[-10:] if tb_lines else []

    # 6. 提取 captured stdout/log
    captured_parts = []
    for section_name in ["Captured stdout call", "Captured stderr call", "Captured log call"]:
        pattern = f"-+ {section_name} -+"
        match = re.search(pattern, log_text)
        if match:
            start = match.end()
            # 找下一个分隔符或结束
            next_sep = re.search(r"^-+ .* -+$", log_text[start:])
            next_fail = re.search(r"^_=+ .+ =+$", log_text[start:])
            end_candidates = []
            if next_sep:
                end_candidates.append(start + next_sep.start())
            if next_fail:
                end_candidates.append(start + next_fail.start())
            end = min(end_candidates) if end_candidates else len(log_text)
            content = log_text[start:end].strip()
            if content:
                captured_parts.append(f"[{section_name}]\n{content[:2000]}")
    result["captured_output"] = "\n\n".join(captured_parts) if captured_parts else ""

    # 7. 提取耗时
    dur_match = re.search(r"=+ \d+ (?:failed|passed|error|skipped).* in ([\d.]+)s =+", log_text)
    if dur_match:
        result["duration_seconds"] = float(dur_match.group(1))

    # 8. 判断 torch 相关性
    torch_keywords = [
        "torch", "pytorch", "cuda", "gpu", "aten", "c10",
        "torch.nn", "torch.nn.functional", "torch.distributed",
        "torch.cuda", "torch.backends", "torch.utils",
        "torch.compile", "torch.export", "torch.fx",
        "RuntimeError: CUDA", "CUDA out of memory",
        "NCCL", "nccl", "torch.distributed",
    ]
    torch_evidence = []
    log_lower = log_text.lower()
    for kw in torch_keywords:
        if kw.lower() in log_lower:
            # 找到包含关键词的行
            for line in log_text.splitlines():
                if kw.lower() in line.lower():
                    torch_evidence.append(line.strip()[:200])
                    break  # 每个关键词只取一行证据
    result["torch_related"] = len(torch_evidence) > 0
    result["torch_evidence"] = torch_evidence[:5]  # 最多5条证据

    return result


# ========== 主逻辑 ==========

def main():
    parser = argparse.ArgumentParser(description="Parse pytest log files and generate error report")
    parser.add_argument("--outputs-dir", required=True, help="Directory containing .log and .exit_code files")
    parser.add_argument("--results-dir", required=True, help="Directory for summary.json and output files")
    parser.add_argument("--tests-dir", required=True, help="Tests directory (for reference in report)")
    args = parser.parse_args()

    outputs_dir = args.outputs_dir
    results_dir = args.results_dir
    tests_dir = args.tests_dir

    # 扫描所有 .log 文件和 .exit_code 文件
    all_results = []
    for filename in sorted(os.listdir(outputs_dir)):
        if not filename.endswith(".log"):
            continue

        safe_name = filename[:-4]  # 去掉 .log
        log_path = os.path.join(outputs_dir, filename)
        exit_code_path = os.path.join(outputs_dir, f"{safe_name}.exit_code")

        # 读取 exit code
        exit_code = -1
        if os.path.exists(exit_code_path):
            try:
                exit_code = int(open(exit_code_path).read().strip())
            except ValueError:
                exit_code = -1

        # 读取 log
        try:
            log_text = open(log_path, "r", errors="replace").read()
        except Exception as e:
            all_results.append({
                "test_file": safe_name,
                "status": "read_error",
                "exception_type": "ReadError",
                "exception_message": str(e),
                "torch_related": False,
            })
            continue

        # 从 safe_name 还原 test_name (大致)
        # safe_name 把 :: -> _ , / -> _ , .// -> _
        # 无法完全还原，但可以用 log 内容中的 pytest summary 行
        test_name = safe_name
        # 尝试从 log 中提取实际的 test node ID
        node_id_match = re.search(r"^(\S+\.py::\S+)", log_text, re.MULTILINE)
        if node_id_match:
            test_name = node_id_match.group(1)
        else:
            # 尝试从 FAILED/ERROR summary 行提取
            summary_match = re.search(r"^(?:FAILED|ERROR)\s+(\S+\.py(?:::\S+)?)", log_text, re.MULTILINE)
            if summary_match:
                test_name = summary_match.group(1)

        parsed = parse_pytest_log(log_text, exit_code, test_name)
        all_results.append(parsed)

    # 过滤出非 passed 的结果
    non_passed = [r for r in all_results if r.get("status") != "passed"]

    # 按 exception_type 分类统计
    exc_type_stats = defaultdict(list)
    for r in non_passed:
        exc_type = r.get("exception_type") or "Unknown"
        exc_type_stats[exc_type].append(r)

    # 每类错误取一个典型样例
    typical_examples = {}
    for exc_type, items in exc_type_stats.items():
        # 选 torch_related 的作为代表（如果有），否则选第一个
        torch_items = [i for i in items if i.get("torch_related")]
        typical = torch_items[0] if torch_items else items[0]
        typical_examples[exc_type] = {
            "count": len(items),
            "torch_related_count": len(torch_items),
            "sample": {
                "test_file": typical["test_file"],
                "exception_message": typical.get("exception_message", "")[:300],
                "failure_location": typical.get("failure_location", ""),
                "traceback_summary": typical.get("traceback_summary", [])[:5],
                "torch_related": typical.get("torch_related", False),
                "torch_evidence": typical.get("torch_evidence", []),
            }
        }

    # torch 相关错误列表
    torch_errors = [r for r in non_passed if r.get("torch_related")]

    # 构建 error_report.json
    report = {
        "generated_at": datetime.now().isoformat(),
        "tests_dir": tests_dir,
        "total_non_passed": len(non_passed),
        "total_torch_related": len(torch_errors),
        "exception_type_catalog": {},
        "torch_related_errors": [],
        "all_non_passed": [],
    }

    # exception_type_catalog: 分类概览
    catalog = {}
    for exc_type, info in sorted(typical_examples.items(), key=lambda x: -x[1]["count"]):
        catalog[exc_type] = {
            "count": info["count"],
            "torch_related_count": info["torch_related_count"],
            "sample_failure_location": info["sample"]["failure_location"],
            "sample_exception_message": info["sample"]["exception_message"],
            "sample_traceback": info["sample"]["traceback_summary"],
            "sample_torch_evidence": info["sample"]["torch_evidence"],
        }
    report["exception_type_catalog"] = catalog

    # torch_related_errors: 简化的 torch 相关错误清单
    for r in torch_errors:
        report["torch_related_errors"].append({
            "test_file": r["test_file"],
            "exception_type": r.get("exception_type", "Unknown"),
            "exception_message": r.get("exception_message", "")[:300],
            "failure_location": r.get("failure_location", ""),
            "torch_evidence": r.get("torch_evidence", []),
            "traceback_summary": r.get("traceback_summary", [])[:5],
            "duration_seconds": r.get("duration_seconds", 0),
            "status": r.get("status", "unknown"),
        })

    # all_non_passed: 全量详情
    for r in non_passed:
        report["all_non_passed"].append({
            "test_file": r["test_file"],
            "status": r.get("status", "unknown"),
            "exit_code": r.get("exit_code", -1),
            "exception_type": r.get("exception_type", "Unknown"),
            "exception_message": r.get("exception_message", "")[:500],
            "failure_location": r.get("failure_location", ""),
            "traceback_summary": r.get("traceback_summary", []),
            "captured_output": r.get("captured_output", "")[:2000],
            "torch_related": r.get("torch_related", False),
            "torch_evidence": r.get("torch_evidence", []),
            "duration_seconds": r.get("duration_seconds", 0),
            "pytest_summary_line": r.get("pytest_summary_line", ""),
        })

    # 写入 error_report.json
    report_path = os.path.join(results_dir, "error_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Error report written to: {report_path}")

    # 更新 summary.json 中的 failed/errors 计数
    summary_path = os.path.join(results_dir, "summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, "r") as f:
            summary = json.load(f)
        failed_count = len([r for r in non_passed if r.get("status") == "failed"])
        error_count = len([r for r in non_passed if r.get("status") == "error"])
        timeout_count = len([r for r in non_passed if r.get("status") == "timeout"])
        summary["failed"] = failed_count
        summary["errors"] = error_count
        summary["timeouts"] = timeout_count
        summary["torch_related"] = len(torch_errors)
        summary["exception_types"] = list(exc_type_stats.keys())
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

    # 打印人类可读的摘要
    print()
    print("=" * 60)
    print("ERROR REPORT SUMMARY")
    print("=" * 60)
    print(f"Total non-passed tests: {len(non_passed)}")
    print(f"Total torch-related:    {len(torch_errors)}")
    print()
    print("Exception type catalog (sorted by frequency):")
    for exc_type, info in sorted(typical_examples.items(), key=lambda x: -x[1]["count"]):
        torch_marker = " [TORCH]" if info["torch_related_count"] > 0 else ""
        print(f"  {exc_type}: {info["count"]} tests{torch_marker}")
        print(f"    Sample: {info["sample"]["exception_message"][:80]}")
        if info["sample"]["failure_location"]:
            print(f"    Location: {info["sample"]["failure_location"]}")
    print("=" * 60)

    # torch 相关错误清单
    if torch_errors:
        print()
        print("TORCH-RELATED ERRORS:")
        for r in torch_errors:
            print(f"  - {r['test_file']}: {r.get('exception_type', '?')} - {r.get('exception_message', '')[:60]}")
        print()


if __name__ == "__main__":
    main()
