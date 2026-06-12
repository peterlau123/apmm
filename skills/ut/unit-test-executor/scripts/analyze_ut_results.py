"""
UT测试结果统计脚本
分析remote_log_summary中的passed/error/failed文件
生成详细统计报告和测试用例清单
"""

import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# 从脚本目录推断路径
_SCRIPT_DIR = Path(__file__).parent
_WORKSPACE = _SCRIPT_DIR.parent.parent.parent.parent
SUMMARY_DIR = _WORKSPACE / "tasks" / "ut" / "remote_log_summary"
OUTPUT_DIR = _WORKSPACE / "tasks" / "ut" / "test_analysis"

def parse_test_case(line):
    """
    解析一行测试结果，提取测试用例ID
    
    格式: ut_logs/<logfile>:<line>:<test_case_id> PASSED/ERROR/FAILED [progress]
    """
    # 提取测试用例ID（tests/...::...部分）
    match = re.search(r'(tests/[^\s]+)\s+(PASSED|ERROR|FAILED)', line)
    if match:
        test_id = match.group(1)
        status = match.group(2)
        return test_id, status
    return None, None

def extract_unique_cases(file_path):
    """
    从文件中提取唯一的测试用例
    
    Returns:
        dict: {test_id: [lines]} 每个测试用例出现的所有行
    """
    cases = defaultdict(list)
    
    try:
        content = file_path.read_text(encoding="utf-8")
        for line in content.strip().split("\n"):
            if line:
                test_id, status = parse_test_case(line)
                if test_id:
                    cases[test_id].append(line)
    except Exception as e:
        print(f"[ERROR] Failed to read {file_path}: {e}")
    
    return cases

def categorize_by_module(test_cases):
    """
    按模块分类测试用例
    
    Returns:
        dict: {module: {test_id: count}}
    """
    modules = defaultdict(dict)
    
    for test_id in test_cases:
        # 提取模块名 (tests/xxx/...)
        parts = test_id.split("/")
        if len(parts) >= 2:
            module = parts[1]  # tests/compile/... -> compile
        else:
            module = "other"
        
        modules[module][test_id] = len(test_cases[test_id])
    
    return modules

def generate_statistics():
    """
    生成完整统计报告
    """
    print("=" * 70)
    print("UT测试结果统计分析")
    print("=" * 70)
    print(f"分析目录: {SUMMARY_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    
    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    # 分析passed文件
    passed_file = SUMMARY_DIR / "passed_ut_cases-20260606.txt"
    if passed_file.exists():
        passed_cases = extract_unique_cases(passed_file)
        passed_modules = categorize_by_module(passed_cases)
        
        results["passed"] = {
            "total_lines": len(passed_file.read_text().strip().split("\n")),
            "unique_cases": len(passed_cases),
            "by_module": {m: len(c) for m, c in passed_modules.items()}
        }
        
        # 保存passed测试用例列表
        passed_list_file = OUTPUT_DIR / "passed_cases_unique.txt"
        with open(passed_list_file, "w", encoding="utf-8") as f:
            for test_id in sorted(passed_cases.keys()):
                f.write(f"{test_id}\n")
        
        print(f"[PASSED] 总行数: {results['passed']['total_lines']}")
        print(f"[PASSED] 唯一用例: {results['passed']['unique_cases']}")
        print(f"[PASSED] 已保存到: {passed_list_file}")
        print()
    else:
        print("[PASSED] 文件不存在")
        results["passed"] = {"total_lines": 0, "unique_cases": 0}
    
    # 分析error文件
    error_file = SUMMARY_DIR / "error_ut_cases-20260606.txt"
    if error_file.exists():
        error_cases = extract_unique_cases(error_file)
        error_modules = categorize_by_module(error_cases)
        
        results["error"] = {
            "total_lines": len(error_file.read_text().strip().split("\n")),
            "unique_cases": len(error_cases),
            "by_module": {m: len(c) for m, c in error_modules.items()}
        }
        
        # 保存error测试用例列表
        error_list_file = OUTPUT_DIR / "error_cases_unique.txt"
        with open(error_list_file, "w", encoding="utf-8") as f:
            for test_id in sorted(error_cases.keys()):
                f.write(f"{test_id}\n")
        
        print(f"[ERROR] 总行数: {results['error']['total_lines']}")
        print(f"[ERROR] 唯一用例: {results['error']['unique_cases']}")
        print(f"[ERROR] 已保存到: {error_list_file}")
        print()
    else:
        print("[ERROR] 文件不存在")
        results["error"] = {"total_lines": 0, "unique_cases": 0}
    
    # 分析failed文件
    failed_file = SUMMARY_DIR / "failed_ut_cases-20260606.txt"
    if failed_file.exists():
        failed_cases = extract_unique_cases(failed_file)
        failed_modules = categorize_by_module(failed_cases)
        
        results["failed"] = {
            "total_lines": len(failed_file.read_text().strip().split("\n")),
            "unique_cases": len(failed_cases),
            "by_module": {m: len(c) for m, c in failed_modules.items()}
        }
        
        # 保存failed测试用例列表
        failed_list_file = OUTPUT_DIR / "failed_cases_unique.txt"
        with open(failed_list_file, "w", encoding="utf-8") as f:
            for test_id in sorted(failed_cases.keys()):
                f.write(f"{test_id}\n")
        
        print(f"[FAILED] 总行数: {results['failed']['total_lines']}")
        print(f"[FAILED] 唯一用例: {results['failed']['unique_cases']}")
        print(f"[FAILED] 已保存到: {failed_list_file}")
        print()
    else:
        print("[FAILED] 文件不存在")
        results["failed"] = {"total_lines": 0, "unique_cases": 0}
    
    # 模块分布统计
    print("=" * 70)
    print("模块分布统计")
    print("=" * 70)
    
    all_modules = set()
    for status in ["passed", "error", "failed"]:
        if results[status].get("by_module"):
            all_modules.update(results[status]["by_module"].keys())
    
    print(f"\n{'模块':<30} {'PASSED':>10} {'ERROR':>10} {'FAILED':>10}")
    print("-" * 60)
    
    for module in sorted(all_modules):
        passed_count = results["passed"]["by_module"].get(module, 0)
        error_count = results["error"]["by_module"].get(module, 0)
        failed_count = results["failed"]["by_module"].get(module, 0)
        print(f"{module:<30} {passed_count:>10} {error_count:>10} {failed_count:>10}")
    
    print("-" * 60)
    total_passed = results["passed"]["unique_cases"]
    total_error = results["error"]["unique_cases"]
    total_failed = results["failed"]["unique_cases"]
    print(f"{'合计':<30} {total_passed:>10} {total_error:>10} {total_failed:>10}")
    print()
    
    # 生成JSON报告
    report_file = OUTPUT_DIR / "test_statistics_report.json"
    report = {
        "analysis_date": datetime.now().isoformat(),
        "source_files": {
            "passed": str(passed_file) if passed_file.exists() else None,
            "error": str(error_file) if error_file.exists() else None,
            "failed": str(failed_file) if failed_file.exists() else None
        },
        "statistics": results,
        "summary": {
            "total_passed_unique": total_passed,
            "total_error_unique": total_error,
            "total_failed_unique": total_failed,
            "total_tested": total_passed + total_error + total_failed
        }
    }
    
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"完整报告已保存到: {report_file}")
    
    return results

def main():
    generate_statistics()

if __name__ == "__main__":
    main()