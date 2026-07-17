#!/usr/bin/env python3
"""
migrate_manifest.py - Manifest JSON 迁移脚本

功能：
- 将旧版本manifest.json迁移到新schema格式
- 字段映射：test_func → test_name, run_at → last_run_at
- error_type映射：单字母编码 → 描述性字符串

迁移规则：
1. test_func → test_name (直接重命名)
2. run_at → last_run_at (直接重命名)
3. phase 字段移除
4. source_files 字段移除
5. error_type 映射：
   - M → download_error
   - A → dependency
   - B → network
   - C → resource
   - D → version
   - E → functional
   - 其他 → other
6. 新增 version: "2.0"
7. 新增 source: "pytest_collect" (默认)

Author: UT Workflow Team
Version: 2.0
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

# ============================================================
# Error Type 映射表
# ============================================================
ERROR_TYPE_MAP = {
    "M": "download_error",  # Model not found, config.json missing
    "A": "dependency",      # ImportError, ModuleNotFoundError
    "B": "network",         # ConnectionError, HTTP 503/404
    "C": "resource",        # CUDA OOM, GPU unavailable
    "D": "version",         # Version compatibility issues
    "E": "functional",      # AssertionError, ValueError
}

# 默认值
DEFAULT_VERSION = "2.0"
DEFAULT_SOURCE = "pytest_collect"


def migrate_test_item(test: dict) -> dict:
    """
    单个测试项迁移

    Args:
        test: 旧版本测试项字典

    Returns:
        新版本测试项字典

    字段迁移：
    - test_func → test_name (直接重命名)
    - run_at → last_run_at (直接重命名)
    - error_type: M/A/B/C/D/E → 描述性字符串
    - error_type: 其他 → other
    - 移除 phase 字段
    - 移除 source_files 字段
    """
    migrated = {}

    # 保留的字段（直接复制）
    preserve_fields = [
        "id", "test_node", "test_file", "status", "priority",
        "batch_id", "run_count", "last_duration_ms", "last_exit_code",
        "error_message", "ignored_reason", "fix_applied", "fix_details", "log_file"
    ]

    for field in preserve_fields:
        if field in test:
            migrated[field] = test[field]

    # 字段重命名
    if "test_func" in test:
        migrated["test_name"] = test["test_func"]
    elif "test_name" in test:
        migrated["test_name"] = test["test_name"]
    else:
        # 如果都没有，尝试从test_node提取
        if "test_node" in test:
            test_node = test["test_node"]
            # 格式: tests/test_file.py::TestClass::test_method
            parts = test_node.split("::")
            if len(parts) >= 3:
                migrated["test_name"] = parts[-1]
            elif len(parts) >= 2:
                migrated["test_name"] = parts[-1]
            else:
                migrated["test_name"] = test_node.split("/")[-1].replace(".py", "")

    if "run_at" in test:
        migrated["last_run_at"] = test["run_at"]
    elif "last_run_at" in test:
        migrated["last_run_at"] = test["last_run_at"]
    else:
        migrated["last_run_at"] = None

    # error_type 映射
    if "error_type" in test:
        old_error_type = test["error_type"]
        if old_error_type is None:
            migrated["error_type"] = None
        elif old_error_type in ERROR_TYPE_MAP:
            migrated["error_type"] = ERROR_TYPE_MAP[old_error_type]
        elif old_error_type in ["dependency", "network", "resource", "version", "functional", "download_error", "other"]:
            # 已经是新格式，直接保留
            migrated["error_type"] = old_error_type
        else:
            # 未知的error_type，映射为other
            migrated["error_type"] = "other"
    else:
        migrated["error_type"] = None

    # 确保status字段存在
    if "status" not in migrated:
        migrated["status"] = "pending"

    return migrated


def migrate_statistics(stats: dict) -> dict:
    """
    迁移统计字段

    Args:
        stats: 旧版本统计字典

    Returns:
        新版本统计字典
    """
    migrated = {}

    # 保留的字段
    preserve_fields = [
        "total", "passed", "failed", "error", "ignored",
        "pending", "pass_rate", "progress", "executed"
    ]

    for field in preserve_fields:
        if field in stats:
            migrated[field] = stats[field]
        else:
            # 设置默认值
            if field == "total":
                migrated[field] = 0
            elif field == "pending":
                migrated[field] = 0
            elif field in ["passed", "failed", "error", "ignored", "executed"]:
                migrated[field] = 0
            elif field in ["pass_rate", "progress"]:
                migrated[field] = 0

    return migrated


def migrate_manifest(
    source_path,
    target_path: Path | None = None,
    backup: bool = True,
    default_max_retry: int = 3,
) -> dict:
    """
    迁移 manifest.json 到新 schema 格式

    支持两种调用方式：
    1. dict-in/dict-out（v5 backward-compat backfill）：
       migrate_manifest(manifest_dict, default_max_retry=3) → migrated_dict
       仅回填缺失的 max_retry 与 last_batch_id 字段，不写文件。
    2. 文件路径 → 文件路径（旧版完整迁移）：
       migrate_manifest(Path("manifest.json")) → 迁移结果统计 dict

    Args:
        source_path: dict 或 Path（旧 manifest.json 路径）
        target_path: 目标路径（仅文件模式）
        backup: 是否创建备份（仅文件模式）
        default_max_retry: 当 max_retry 缺失时的默认值（dict 模式回填使用）

    Returns:
        dict 模式：迁移后的 manifest dict
        文件模式：迁移结果统计 dict
    """
    # ---- v5 dict-in/dict-out backfill mode ----
    if isinstance(source_path, dict):
        manifest = source_path
        migrated = dict(manifest)
        new_tests = []
        for test in manifest.get("tests", []):
            t = dict(test)
            if "max_retry" not in t:
                t["max_retry"] = default_max_retry
            if "last_batch_id" not in t:
                t["last_batch_id"] = None
            new_tests.append(t)
        migrated["tests"] = new_tests
        return migrated

    # ---- legacy file-based full migration ----
    if target_path is None:
        target_path = source_path

    # 加载源文件
    with open(source_path, "r", encoding="utf-8") as f:
        old_manifest = json.load(f)

    # 创建新manifest
    new_manifest = {}

    # 添加版本和来源
    new_manifest["version"] = DEFAULT_VERSION
    new_manifest["generated_at"] = old_manifest.get("generated_at") or datetime.now().isoformat()
    new_manifest["source"] = old_manifest.get("source") or DEFAULT_SOURCE

    # 迁移config（如果存在）
    if "config" in old_manifest:
        new_manifest["config"] = old_manifest["config"]

    # 迁移tests
    old_tests = old_manifest.get("tests", [])
    new_tests = []
    error_type_mappings = {}

    for test in old_tests:
        migrated_test = migrate_test_item(test)
        new_tests.append(migrated_test)

        # 记录error_type映射统计
        old_error_type = test.get("error_type")
        new_error_type = migrated_test.get("error_type")
        if old_error_type != new_error_type:
            key = f"{old_error_type} → {new_error_type}"
            error_type_mappings[key] = error_type_mappings.get(key, 0) + 1

    new_manifest["tests"] = new_tests

    # 迁移statistics
    old_stats = old_manifest.get("statistics", {})
    new_stats = migrate_statistics(old_stats)

    # 更新统计数据（基于迁移后的tests）
    new_stats["total"] = len(new_tests)
    new_stats["pending"] = sum(1 for t in new_tests if t.get("status") == "pending")
    new_stats["passed"] = sum(1 for t in new_tests if t.get("status") == "passed")
    new_stats["failed"] = sum(1 for t in new_tests if t.get("status") == "failed")
    new_stats["error"] = sum(1 for t in new_tests if t.get("status") == "error")
    new_stats["ignored"] = sum(1 for t in new_tests if t.get("status") == "ignored")
    new_stats["executed"] = new_stats["passed"] + new_stats["failed"] + new_stats["error"] + new_stats["ignored"]

    if new_stats["total"] > 0:
        new_stats["progress"] = round((new_stats["executed"] / new_stats["total"]) * 100, 2)
        new_stats["pass_rate"] = round((new_stats["passed"] / new_stats["executed"]) * 100, 2) if new_stats["executed"] > 0 else 0

    new_manifest["statistics"] = new_stats

    # 迁移metadata（如果存在）
    if "metadata" in old_manifest:
        new_manifest["metadata"] = old_manifest["metadata"]

    # 创建备份
    backup_path = None
    if backup and source_path.exists():
        backup_path = source_path.parent / "manifest_legacy.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(old_manifest, f, indent=2, ensure_ascii=False)

    # 写入新文件
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=2, ensure_ascii=False)

    # 返回迁移统计
    return {
        "source": str(source_path),
        "target": str(target_path),
        "backup": str(backup_path) if backup_path else None,
        "tests_count": len(old_tests),
        "migrated_count": len(new_tests),
        "error_type_mappings": error_type_mappings,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# CLI 支持
# ============================================================

def cli_main():
    """
    CLI入口：执行迁移

    Usage:
        python migrate_manifest.py <source_path> [target_path]
        python migrate_manifest.py tasks/ut/test_analysis/manifest.json
        python migrate_manifest.py tasks/ut/test_analysis/manifest.json tasks/ut/test_analysis/manifest_new.json
    """
    if len(sys.argv) < 2:
        print("Usage: python migrate_manifest.py <source_path> [target_path]")
        print("Options:")
        print("  --no-backup    不创建备份文件")
        sys.exit(1)

    source_path = Path(sys.argv[1])
    target_path = Path(sys.argv[2]) if len(sys.argv) >= 3 and not sys.argv[2].startswith("--") else None

    # 检查是否禁用备份
    backup = "--no-backup" not in sys.argv

    if not source_path.exists():
        print(f"[ERROR] Source file not found: {source_path}")
        sys.exit(1)

    # 执行迁移
    result = migrate_manifest(source_path, target_path, backup)

    print("[OK] Manifest migration completed:")
    print(f"  Source: {result['source']}")
    print(f"  Target: {result['target']}")
    if result['backup']:
        print(f"  Backup: {result['backup']}")
    print(f"  Tests: {result['tests_count']} → {result['migrated_count']}")

    if result['error_type_mappings']:
        print("  Error type mappings:")
        for mapping, count in result['error_type_mappings'].items():
            print(f"    {mapping}: {count} tests")


if __name__ == "__main__":
    cli_main()