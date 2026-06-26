"""
标记已通过测试用例为无需运行
对比passed_cases_unique.txt与ut_test_list.txt/ut_test_list_full.txt
生成新的测试列表（排除已通过的用例）
"""

import json
from pathlib import Path
from datetime import datetime

# 从脚本目录推断路径
BASE_DIR = Path(__file__).parent.parent.parent.parent / "tasks" / "ut"
ANALYSIS_DIR = BASE_DIR / "test_analysis"
OUTPUT_DIR = BASE_DIR / "test_lists_marked"

def load_passed_cases():
    """加载已通过的测试用例列表"""
    passed_file = ANALYSIS_DIR / "passed_cases_unique.txt"
    passed_cases = set()
    
    if passed_file.exists():
        content = passed_file.read_text(encoding="utf-8")
        for line in content.strip().split("\n"):
            if line.strip():
                passed_cases.add(line.strip())
    
    return passed_cases

def load_test_list(file_name):
    """加载测试列表文件"""
    test_file = BASE_DIR / file_name
    test_cases = []
    
    if test_file.exists():
        content = test_file.read_text(encoding="utf-8")
        for line in content.strip().split("\n"):
            if line.strip():
                test_cases.append(line.strip())
    
    return test_cases

def generate_marked_lists():
    """生成标记后的测试列表"""
    print("=" * 70)
    print("标记已通过测试用例")
    print("=" * 70)
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 加载已通过的用例
    passed_cases = load_passed_cases()
    print(f"\n已通过测试用例: {len(passed_cases)}")
    
    # 处理ut_test_list.txt
    test_list = load_test_list("ut_test_list.txt")
    print(f"ut_test_list.txt 测试用例总数: {len(test_list)}")
    
    # 分类：passed vs to_run
    passed_in_list = []
    to_run = []
    
    for test_case in test_list:
        if test_case in passed_cases:
            passed_in_list.append(test_case)
        else:
            to_run.append(test_case)
    
    print(f"  - 已通过（无需运行）: {len(passed_in_list)}")
    print(f"  - 待运行: {len(to_run)}")
    
    # 保存待运行列表
    to_run_file = OUTPUT_DIR / "ut_test_list_to_run.txt"
    to_run_file.write_text("\n".join(to_run), encoding="utf-8")
    print(f"  - 已保存待运行列表: {to_run_file}")
    
    # 保存已通过列表（用于验证）
    passed_marked_file = OUTPUT_DIR / "ut_test_list_passed.txt"
    passed_marked_file.write_text("\n".join(passed_in_list), encoding="utf-8")
    
    # 处理ut_test_list_full.txt
    test_list_full = load_test_list("ut_test_list_full.txt")
    # 去掉第一行（Running xxx items）
    if test_list_full and test_list_full[0].startswith("Running"):
        test_list_full = test_list_full[1:]
    
    print(f"\nut_test_list_full.txt 测试用例总数: {len(test_list_full)}")
    
    passed_in_full = []
    to_run_full = []
    
    for test_case in test_list_full:
        if test_case in passed_cases:
            passed_in_full.append(test_case)
        else:
            to_run_full.append(test_case)
    
    print(f"  - 已通过（无需运行）: {len(passed_in_full)}")
    print(f"  - 待运行: {len(to_run_full)}")
    
    # 保存待运行列表
    to_run_full_file = OUTPUT_DIR / "ut_test_list_full_to_run.txt"
    to_run_full_file.write_text("\n".join(to_run_full), encoding="utf-8")
    print(f"  - 已保存待运行列表: {to_run_full_file}")
    
    # 保存已通过列表
    passed_full_file = OUTPUT_DIR / "ut_test_list_full_passed.txt"
    passed_full_file.write_text("\n".join(passed_in_full), encoding="utf-8")
    
    # 生成汇总报告
    summary = {
        "analysis_date": datetime.now().isoformat(),
        "passed_cases_from_logs": len(passed_cases),
        "ut_test_list": {
            "total": len(test_list),
            "passed": len(passed_in_list),
            "to_run": len(to_run),
            "passed_ratio": round(len(passed_in_list) / len(test_list) * 100, 2) if test_list else 0
        },
        "ut_test_list_full": {
            "total": len(test_list_full),
            "passed": len(passed_in_full),
            "to_run": len(to_run_full),
            "passed_ratio": round(len(passed_in_full) / len(test_list_full) * 100, 2) if test_list_full else 0
        },
        "output_files": {
            "ut_test_list_to_run": str(to_run_file),
            "ut_test_list_full_to_run": str(to_run_full_file)
        }
    }
    
    summary_file = OUTPUT_DIR / "marked_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n汇总报告已保存: {summary_file}")
    
    return summary

def main():
    generate_marked_lists()

if __name__ == "__main__":
    main()