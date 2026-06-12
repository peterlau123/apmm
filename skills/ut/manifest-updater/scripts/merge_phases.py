#!/usr/bin/env python3
"""
合并 Phase 1 和 Phase 2 的测试清单和 manifest.json

规则：
1. 求并集：两个phase的所有测试项都保留
2. 状态同步：
   - 重叠测试项：如果任一phase有执行结果（passed/failed），同步到另一phase
   - failed优先：如果phase1=failed，phase2也要failed
3. 重新计算statistics
4. 生成合并后的 test_list.txt 和 manifest.json

用法：
    python merge_phases.py [--dry-run]
"""

import json
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# 定义路径
SCRIPT_DIR = Path(__file__).parent
TEST_ANALYSIS_DIR = SCRIPT_DIR.parent / "test_analysis"
ARCHIVE_DIR = TEST_ANALYSIS_DIR / "archive"

PHASE1_MANIFEST = ARCHIVE_DIR / "phase1_manifest_20260608_232517.json"
PHASE2_MANIFEST = ARCHIVE_DIR / "phase2_manifest_20260608_232517.json"
PHASE1_TESTLIST = ARCHIVE_DIR / "phase1_test_list_20260608_232517.txt"
PHASE2_TESTLIST = ARCHIVE_DIR / "phase2_test_list_20260608_232517.txt"

OUTPUT_MANIFEST = TEST_ANALYSIS_DIR / "manifest.json"
OUTPUT_TESTLIST = TEST_ANALYSIS_DIR / "test_list.txt"

# 状态优先级：failed > passed > pending
STATUS_PRIORITY = {"failed": 3, "error": 3, "passed": 2, "pending": 1, "ignored": 0}


def load_manifest(filepath):
    """加载 manifest.json"""
    print(f"加载 {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def load_testlist(filepath):
    """加载测试清单"""
    print(f"加载 {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines


def merge_tests(phase1_tests, phase2_tests):
    """
    合并两个phase的测试项

    规则：
    1. test_node 作为唯一标识
    2. 如果两个phase都有同一个test_node：
       - 如果phase1有执行结果（passed/failed/error），使用phase1的状态
       - 如果phase1=failed/error，phase2也同步为failed/error
       - 如果都只有pending，合并phase标记
    3. 如果只有一个phase有，保留该测试项
    """
    # 构建 test_node -> test 索引
    phase1_index = {t["test_node"]: t for t in phase1_tests}
    phase2_index = {t["test_node"]: t for t in phase2_tests}

    # 过滤无效测试项（如 "Running 31372 items in this shard"）
    valid_phase2_tests = {
        node: t for node, t in phase2_index.items()
        if node.startswith("tests/")
    }

    # 合并结果
    merged_tests = []
    seen_nodes = set()

    # 统计
    stats = {
        "total": 0,
        "phase1_only": 0,
        "phase2_only": 0,
        "both": 0,
        "status_synced": 0,
    }

    # 先处理phase1的测试项
    for test_node, test in phase1_index.items():
        if test_node in seen_nodes:
            continue
        seen_nodes.add(test_node)

        # 检查phase2是否也有
        if test_node in valid_phase2_tests:
            stats["both"] += 1
            phase2_test = valid_phase2_tests[test_node]

            # 状态同步规则
            merged_test = merge_single_test(test, phase2_test)
            if merged_test["_synced"]:
                stats["status_synced"] += 1
            del merged_test["_synced"]

            merged_tests.append(merged_test)
        else:
            stats["phase1_only"] += 1
            merged_test = test.copy()
            merged_test["phase"] = "phase1"
            merged_tests.append(merged_test)

    # 处理phase2独有的测试项
    for test_node, test in valid_phase2_tests.items():
        if test_node in seen_nodes:
            continue
        seen_nodes.add(test_node)

        stats["phase2_only"] += 1
        merged_test = test.copy()
        merged_tests.append(merged_test)

    stats["total"] = len(merged_tests)

    return merged_tests, stats


def merge_single_test(phase1_test, phase2_test):
    """
    合并单个测试项

    状态同步规则：
    1. 如果phase1=failed/error，使用phase1状态
    2. 如果phase1=passed，phase2=pending，使用phase1状态
    3. 如果phase1=pending，phase2有执行结果，使用phase2状态
    4. 如果都有执行结果，取优先级高的状态
    """
    p1_status = phase1_test.get("status", "pending")
    p2_status = phase2_test.get("status", "pending")

    synced = False
    merged = None

    # 规则1: phase1 failed/error 优先
    if p1_status in ("failed", "error"):
        merged = phase1_test.copy()
        merged["phase"] = "phase1"
        if p2_status != p1_status:
            synced = True

    # 规则2: phase1 passed
    elif p1_status == "passed":
        merged = phase1_test.copy()
        merged["phase"] = "phase1"
        if p2_status == "pending":
            synced = True

    # 规则3: phase1 pending，phase2有执行结果
    elif p1_status == "pending" and p2_status in ("passed", "failed", "error"):
        merged = phase2_test.copy()
        merged["phase"] = "phase2"
        synced = True

    # 规则4: 都是pending或有其他状态，优先级高的
    else:
        p1_priority = STATUS_PRIORITY.get(p1_status, 0)
        p2_priority = STATUS_PRIORITY.get(p2_status, 0)

        if p1_priority >= p2_priority:
            merged = phase1_test.copy()
            merged["phase"] = "phase1"
        else:
            merged = phase2_test.copy()
            merged["phase"] = "phase2"

    merged["_synced"] = synced
    return merged


def calculate_statistics(tests):
    """计算统计数据"""
    stats = {
        "pending": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "ignored": 0,
        "total": len(tests),
    }

    for test in tests:
        status = test.get("status", "pending")
        if status in stats:
            stats[status] += 1
        else:
            # 未知状态算作pending
            stats["pending"] += 1

    stats["executed"] = stats["passed"] + stats["failed"] + stats["error"]
    stats["progress"] = round(stats["executed"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0

    return stats


def generate_testlist(tests):
    """生成测试清单文本"""
    lines = []
    for test in tests:
        lines.append(test["test_node"])
    return lines


def main():
    parser = argparse.ArgumentParser(description="合并 Phase 1 和 Phase 2 的测试清单")
    parser.add_argument("--dry-run", action="store_true", help="仅显示统计，不写入文件")
    args = parser.parse_args()

    print("=" * 60)
    print("合并 Phase 1 和 Phase 2 测试清单")
    print("=" * 60)

    # 加载数据
    phase1_manifest = load_manifest(PHASE1_MANIFEST)
    phase2_manifest = load_manifest(PHASE2_MANIFEST)

    phase1_tests = phase1_manifest.get("tests", [])
    phase2_tests = phase2_manifest.get("tests", [])

    # 过滤phase2中的无效项
    phase2_tests_valid = [
        t for t in phase2_tests
        if t["test_node"].startswith("tests/")
    ]

    print(f"\nPhase 1 测试项: {len(phase1_tests)}")
    print(f"Phase 2 测试项: {len(phase2_tests)} (有效: {len(phase2_tests_valid)})")

    # 合并测试项
    merged_tests, merge_stats = merge_tests(phase1_tests, phase2_tests_valid)

    # 计算统计
    statistics = calculate_statistics(merged_tests)

    # 生成输出
    testlist_lines = generate_testlist(merged_tests)

    # 构建manifest
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "source_files": [
            "phase1_manifest.json",
            "phase2_manifest.json"
        ],
        "total_tests": statistics["total"],
        "statistics": statistics,
        "tests": merged_tests,
    }

    # 打印统计
    print("\n" + "=" * 60)
    print("合并统计")
    print("=" * 60)
    print(f"总测试项: {merge_stats['total']}")
    print(f"Phase 1 独有: {merge_stats['phase1_only']}")
    print(f"Phase 2 独有: {merge_stats['phase2_only']}")
    print(f"两者共有: {merge_stats['both']}")
    print(f"状态同步: {merge_stats['status_synced']}")
    print()
    print("执行统计:")
    print(f"  Passed: {statistics['passed']}")
    print(f"  Failed: {statistics['failed']}")
    print(f"  Error: {statistics['error']}")
    print(f"  Pending: {statistics['pending']}")
    print(f"  Ignored: {statistics['ignored']}")
    print(f"  已执行: {statistics['executed']} ({statistics['progress']}%)")

    if args.dry_run:
        print("\n[DRY RUN] 未写入文件")
        return

    # 写入文件
    print("\n写入文件...")
    with open(OUTPUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"✓ {OUTPUT_MANIFEST}")

    with open(OUTPUT_TESTLIST, "w", encoding="utf-8") as f:
        f.write("\n".join(testlist_lines))
    print(f"✓ {OUTPUT_TESTLIST}")

    print("\n完成！")


if __name__ == "__main__":
    main()