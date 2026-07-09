#!/usr/bin/env python3
"""
update_batch_state.py - Batch完成时更新workflow_state.json和test_load.json

新逻辑：
- Batch完成时调用此脚本
- 更新workflow_state.json（batch状态和统计）
- 更新test_load_xxx.json（test状态和统计）

用法：
    python update_batch_state.py \\
        --workflow-state runs/ut-20260708/workflow_state.json \\
        --test-load runs/ut-20260708/test_load_1000_20260708_123456.json \\
        --batch-id batch_20260708_130000 \\
        --batch-results runs/ut-20260708/batches/batch_20260708_130000/batch_results.json
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict


def update_workflow_state(workflow_state_path: Path, batch_id: str, batch_results: dict):
    """更新workflow_state.json

    Args:
        workflow_state_path: workflow_state.json路径
        batch_id: batch ID
        batch_results: batch_results.json内容

    Raises:
        ValueError: 如果JSON解析失败
    """
    try:
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in workflow_state: {workflow_state_path}\n{e}")

    # 更新batch状态
    if batch_id in state.get("batches", {}):
        state["batches"][batch_id]["status"] = "completed"
        state["batches"][batch_id]["completed_at"] = datetime.now().isoformat()

        # 更新batch统计
        stats = batch_results.get("stats", {})
        state["batches"][batch_id]["stats"] = stats

    # 重新计算batch_stats
    batch_stats = {"generated": 0, "running": 0, "completed": 0, "failed": 0}
    for bid, binfo in state.get("batches", {}).items():
        status = binfo.get("status", "generated")
        if status in batch_stats:
            batch_stats[status] += 1

    state["batch_stats"] = batch_stats

    # 更新test_stats
    test_stats = state.get("test_stats", {})
    for key in ["passed", "failed", "error", "ignored"]:
        if key not in test_stats:
            test_stats[key] = 0

    # 从batch_results累加
    batch_stats_result = batch_results.get("stats", {})
    test_stats["passed"] += batch_stats_result.get("passed", 0)
    test_stats["failed"] += batch_stats_result.get("failed", 0)
    test_stats["error"] += batch_stats_result.get("error", 0)
    test_stats["ignored"] += batch_stats_result.get("ignored", 0)

    state["test_stats"] = test_stats

    # 更新时间戳
    state["last_update"] = datetime.now().isoformat()

    # 写回
    workflow_state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"[OK] workflow_state.json已更新")
    print(f"     batch {batch_id}: completed")
    print(f"     batch_stats: {batch_stats}")


def update_test_load(test_load_path: Path, batch_results: dict):
    """更新test_load_xxx.json

    Args:
        test_load_path: test_load_xxx.json路径
        batch_results: batch_results.json内容

    Raises:
        ValueError: 如果JSON解析失败
    """
    try:
        test_load = json.loads(test_load_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in test_load: {test_load_path}\n{e}")

    # 更新test状态
    batch_id = batch_results.get("batch_id", "unknown")
    for result_test in batch_results.get("tests", []):
        test_node = result_test.get("test_node")

        # 查找对应test
        for test in test_load["tests"]:
            if test.get("test_node") == test_node:
                test["status"] = result_test.get("status", "pending")
                test["executed_at"] = datetime.now().isoformat()
                test["batch_id"] = batch_id

                if "error_type" in result_test:
                    test["error_type"] = result_test["error_type"]
                if "error_message" in result_test:
                    test["error_message"] = result_test["error_message"]
                break

    # 重新计算statistics
    stats = defaultdict(int)
    for test in test_load["tests"]:
        status = test.get("status", "pending")
        stats[status] += 1

    test_load["statistics"] = dict(stats)

    # 写回
    test_load_path.write_text(
        json.dumps(test_load, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"[OK] test_load.json已更新")
    print(f"     statistics: {test_load['statistics']}")


def main():
    parser = argparse.ArgumentParser(description="Batch完成后更新状态")
    parser.add_argument(
        "--workflow-state",
        required=True,
        help="workflow_state.json路径"
    )
    parser.add_argument(
        "--test-load",
        required=True,
        help="test_load_xxx.json路径"
    )
    parser.add_argument(
        "--batch-id",
        required=True,
        help="batch ID"
    )
    parser.add_argument(
        "--batch-results",
        required=True,
        help="batch_results.json路径"
    )

    args = parser.parse_args()

    # 读取batch_results（添加JSON错误处理）
    batch_results_path = Path(args.batch_results)
    try:
        batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in batch_results: {batch_results_path}\n{e}")

    # 更新workflow_state.json
    workflow_state_path = Path(args.workflow_state)
    update_workflow_state(workflow_state_path, args.batch_id, batch_results)

    # 更新test_load.json
    test_load_path = Path(args.test_load)
    update_test_load(test_load_path, batch_results)


if __name__ == "__main__":
    main()