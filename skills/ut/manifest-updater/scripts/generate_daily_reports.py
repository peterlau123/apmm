#!/usr/bin/env python3
"""
每日测试报告生成脚本

功能：
1. 更新 progress.md（头部插入统计块，带时间戳）
2. 生成测试报告_<时间戳>.md
3. 生成失败分析报告_<时间戳>.md

使用方法：
    python generate_daily_reports.py
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import re

# 路径配置（相对于项目根目录）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TEST_ANALYSIS_DIR = PROJECT_ROOT / "tasks" / "ut" / "test_analysis"
MANIFEST_FILE = TEST_ANALYSIS_DIR / "manifest.json"
PROGRESS_FILE = PROJECT_ROOT / "tasks" / "ut" / "PROGRESS.md"
REPORT_DIR = TEST_ANALYSIS_DIR / "reports"

# 确保报告目录存在
REPORT_DIR.mkdir(exist_ok=True)


def load_manifest():
    """加载 manifest.json"""
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"Manifest 文件不存在: {MANIFEST_FILE}")
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def calculate_statistics(tests):
    """计算统计信息"""
    stats = defaultdict(int)
    for test in tests:
        status = test.get("status", "pending")
        stats[status] += 1
    
    total = len(tests)
    executed = total - stats.get("pending", 0) - stats.get("todo", 0)
    progress = (executed / total * 100) if total > 0 else 0.0
    
    stats["total"] = total
    stats["executed"] = executed
    stats["progress"] = round(progress, 2)
    
    return dict(stats)


def generate_test_report(manifest: dict, timestamp: str) -> str:
    """生成测试报告"""
    tests = manifest.get("tests", [])
    stats = calculate_statistics(tests)
    
    version_mismatch = sum(1 for t in tests if t.get("version_mismatch_related", False))
    
    # 按文件分组统计
    file_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "error": 0, "pending": 0})
    for test in tests:
        test_file = test.get("test_file", "unknown")
        status = test.get("status", "pending")
        file_stats[test_file][status] += 1
    
    lines = [
        f"# 单元测试报告",
        f"",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        "---",
        "",
        "## 总体统计",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总测试用例数 | {stats.get('total', 0)} |",
        f"| 已执行用例数 | {stats.get('executed', 0)} |",
        f"| 进度 | {stats.get('progress', 0):.2f}% |",
        f"| 通过数 | {stats.get('passed', 0)} |",
        f"| 失败数 | {stats.get('failed', 0)} |",
        f"| 错误数 | {stats.get('error', 0)} |",
        f"| 待执行数 | {stats.get('pending', 0)} |",
        f"| 版本错配相关 | {version_mismatch} |",
        "",
        "---",
        "",
        "## 按测试文件分布（前20个文件）",
        "",
        "| 测试文件 | passed | failed | error | pending |",
        "|----------|--------|--------|-------|---------|",
    ]
    
    sorted_files = sorted(
        file_stats.items(),
        key=lambda x: x[1]["passed"] + x[1]["failed"] + x[1]["error"],
        reverse=True
    )[:20]
    
    for file_path, fstats in sorted_files:
        lines.append(f"| `{file_path}` | {fstats['passed']} | {fstats['failed']} | {fstats['error']} | {fstats['pending']} |")
    
    lines.extend([
        "",
        "---",
        "",
        f"*报告文件: 测试报告_{timestamp}.md*",
    ])
    
    report_content = "\n".join(lines)
    report_file = REPORT_DIR / f"测试报告_{timestamp}.md"
    report_file.write_text(report_content, encoding="utf-8")
    
    return str(report_file)


def generate_failure_analysis(manifest: dict, timestamp: str) -> str:
    """生成失败分析报告"""
    tests = manifest.get("tests", [])
    
    failed_tests = [t for t in tests if t.get("status") == "failed"]
    error_tests = [t for t in tests if t.get("status") == "error"]
    
    # 按错误类型分组
    error_types = defaultdict(list)
    for test in failed_tests + error_tests:
        error_msg = test.get("error_message") or test.get("failed_message") or "未知错误"
        error_type = error_msg.split("\n")[0][:100] if error_msg else "未知错误"
        error_types[error_type].append(test.get("test_node", "unknown"))
    
    version_mismatch_failed = [
        t for t in failed_tests + error_tests
        if t.get("version_mismatch_related", False)
    ]
    
    lines = [
        f"# 失败分析报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 概述",
        "",
        f"- 失败用例数: {len(failed_tests)}",
        f"- 错误用例数: {len(error_tests)}",
        f"- 版本错配相关: {len(version_mismatch_failed)}",
        "",
        "---",
        "",
        "## 失败用例详情",
        "",
    ]
    
    if failed_tests:
        for test in failed_tests[:50]:
            lines.append(f"### {test.get('test_node', 'unknown')}")
            lines.append("")
            if test.get("failed_message"):
                lines.append(f"**失败信息**:")
                lines.append(f"```")
                lines.append(test.get("failed_message", "")[:500])
                lines.append(f"```")
            if test.get("version_mismatch_related"):
                lines.append(f"⚠️ **版本错配相关**: true")
            lines.append("")
    else:
        lines.append("暂无失败用例")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## 错误用例详情",
        "",
    ])
    
    if error_tests:
        for test in error_tests[:50]:
            lines.append(f"### {test.get('test_node', 'unknown')}")
            lines.append("")
            if test.get("error_message"):
                lines.append(f"**错误信息**:")
                lines.append(f"```")
                lines.append(test.get("error_message", "")[:500])
                lines.append(f"```")
            if test.get("version_mismatch_related"):
                lines.append(f"⚠️ **版本错配相关**: true")
            lines.append("")
    else:
        lines.append("暂无错误用例")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## 错误类型分组",
        "",
    ])
    
    if error_types:
        for error_type, test_nodes in sorted(error_types.items(), key=lambda x: -len(x[1])):
            lines.append(f"### {error_type}")
            lines.append(f"涉及 {len(test_nodes)} 个测试:")
            for node in test_nodes[:10]:
                lines.append(f"- `{node}`")
            if len(test_nodes) > 10:
                lines.append(f"- ... 等 {len(test_nodes) - 10} 个")
            lines.append("")
    else:
        lines.append("暂无错误分组")
    
    lines.extend([
        "",
        "---",
        "",
        f"*报告文件: 失败分析报告_{timestamp}.md*",
    ])
    
    report_content = "\n".join(lines)
    report_file = REPORT_DIR / f"失败分析报告_{timestamp}.md"
    report_file.write_text(report_content, encoding="utf-8")
    
    return str(report_file)


def update_progress_md(stats: dict, timestamp: str):
    """更新 progress.md"""
    if not PROGRESS_FILE.exists():
        print(f"警告: PROGRESS.md 不存在 - {PROGRESS_FILE}")
        return
    
    content = PROGRESS_FILE.read_text(encoding="utf-8")
    
    stats_block = [
        f"<!-- STATS_UPDATE_{timestamp} -->",
        f"",
        f"### 📊 最新统计 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
        f"",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总测试用例数 | {stats.get('total', 0)} |",
        f"| 已执行用例数 | {stats.get('executed', 0)} |",
        f"| 进度 | {stats.get('progress', 0):.2f}% |",
        f"| 通过数 | {stats.get('passed', 0)} |",
        f"| 失败数 | {stats.get('failed', 0)} |",
        f"| 错误数 | {stats.get('error', 0)} |",
        f"| 待执行数 | {stats.get('pending', 0)} |",
        f"",
        f"<!-- END_STATS_UPDATE -->",
        f"",
    ]
    
    stats_marker = "<!-- STATS_UPDATE_"
    
    if stats_marker in content:
        pattern = r'<!-- STATS_UPDATE_\d+ -->.*?<!-- END_STATS_UPDATE -->'
        new_block = "\n".join(stats_block)
        content = re.sub(pattern, new_block, content, flags=re.DOTALL)
    else:
        insert_pos = 0
        for i, line in enumerate(content.split("\n")):
            if line.startswith("##") or line.startswith("---"):
                insert_pos = i
                break
        
        lines = content.split("\n")
        new_lines = lines[:insert_pos] + stats_block + lines[insert_pos:]
        content = "\n".join(new_lines)
    
    PROGRESS_FILE.write_text(content, encoding="utf-8")
    print(f"PROGRESS.md 已更新")


def main():
    print("=" * 60)
    print("每日测试报告生成")
    print("=" * 60)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    manifest = load_manifest()
    tests = manifest.get("tests", [])
    stats = calculate_statistics(tests)
    
    print(f"\n加载测试数: {len(tests)}")
    print(f"统计: {stats}")
    
    # 1. 更新 progress.md
    print(f"\n[Step 1] 更新 PROGRESS.md...")
    update_progress_md(stats, timestamp)
    
    # 2. 生成测试报告
    print(f"\n[Step 2] 生成测试报告...")
    test_report_file = generate_test_report(manifest, timestamp)
    print(f"  -> {test_report_file}")
    
    # 3. 生成失败分析报告
    print(f"\n[Step 3] 生成失败分析报告...")
    failure_report_file = generate_failure_analysis(manifest, timestamp)
    print(f"  -> {failure_report_file}")
    
    # 4. 输出摘要（用于飞书）
    print(f"\n[摘要]")
    print(json.dumps({
        "timestamp": timestamp,
        "stats": stats,
        "files": {
            "test_report": test_report_file,
            "failure_analysis": failure_report_file
        }
    }, indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 60)
    print("报告生成完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()