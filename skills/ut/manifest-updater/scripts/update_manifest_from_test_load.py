#!/usr/bin/env python3
"""
update_manifest_from_test_load.py - test_load完成后一次性更新manifest.json

新逻辑：
- test_load_xxx.json全部运行完成后调用此脚本
- 从test_load_xxx.json读取最终状态
- 一次性更新manifest.json（不频繁IO）

用法：
    python update_manifest_from_test_load.py \\
        --manifest-path runs/ut-20260708/manifest.json \\
        --test-load-path runs/ut-20260708/test_load_1000_20260708_123456.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.manifest_updater.scripts.update_status import calculate_statistics


def update_manifest_from_test_load(manifest_path: Path, test_load_path: Path):
    """从test_load更新manifest

    Args:
        manifest_path: 原始manifest.json路径
        test_load_path: test_load_xxx.json路径

    Raises:
        ValueError: 如果test_load未完成（pending > 0）或JSON解析失败
    """
    # 读取manifest（添加JSON错误处理）
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in manifest: {manifest_path}\n{e}")

    manifest_tests = {t["test_node"]: t for t in manifest["tests"]}

    # 读取test_load（添加JSON错误处理）
    try:
        test_load = json.loads(test_load_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in test_load: {test_load_path}\n{e}")

    # Issue 2: 检查test_load是否完全完成（pending == 0）
    statistics = test_load.get("statistics", {})
    pending_count = statistics.get("pending", 0)

    if pending_count > 0:
        raise ValueError(
            f"test_load未完成，仍有 {pending_count} 个pending test。\n"
            f"请等待所有batch完成后再更新manifest。\n"
            f"当前statistics: {statistics}"
        )

    print(f"[INFO] 从test_load更新manifest")
    print(f"       test_load: {len(test_load['tests'])} tests")
    print(f"       manifest: {len(manifest['tests'])} tests")

    # 更新manifest中的test状态
    updated_count = 0
    for test_load_test in test_load["tests"]:
        test_node = test_load_test["test_node"]

        if test_node in manifest_tests:
            # 更新状态
            manifest_tests[test_node]["status"] = test_load_test.get("status", "pending")

            # Copy v5 merge fields (retry_count, ignore_reason, etc.)
            for field in ("retry_count", "ignore_reason", "error_type", "error_message",
                          "last_batch_id", "commit", "errors", "failures",
                          "duration_ms", "exit_code", "log_file", "run_at"):
                if field in test_load_test:
                    manifest_tests[test_node][field] = test_load_test[field]

            # 记录batch执行历史
            if "batch_id" in test_load_test:
                if "batch_history" not in manifest_tests[test_node]:
                    manifest_tests[test_node]["batch_history"] = []
                manifest_tests[test_node]["batch_history"].append({
                    "batch_id": test_load_test["batch_id"],
                    "status": test_load_test["status"],
                    "executed_at": test_load_test.get("executed_at", datetime.now().isoformat())
                })

            updated_count += 1

    # Recalculate statistics using shared function
    manifest["statistics"] = calculate_statistics(manifest["tests"])

    # 更新时间戳
    manifest["generated_at"] = datetime.now().isoformat()
    manifest["test_load_source"] = str(test_load_path)

    # 写回manifest
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"[OK] manifest已更新: {updated_count} tests")
    print(f"     Statistics: {manifest['statistics']}")


def main():
    parser = argparse.ArgumentParser(description="从test_load更新manifest")
    parser.add_argument(
        "--manifest-path",
        required=True,
        help="manifest.json路径"
    )
    parser.add_argument(
        "--test-load-path",
        required=True,
        help="test_load_xxx.json路径"
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest_path)
    test_load_path = Path(args.test_load_path)

    update_manifest_from_test_load(manifest_path, test_load_path)


if __name__ == "__main__":
    main()