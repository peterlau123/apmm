"""
Orchestrator Round - Kanban 调度循环逻辑

职责：
1. 监控 batch-selector task 完成状态
2. 调用 kanban_task_creator 创建依赖链
3. 提交 tasks 到 Hermes Kanban
4. 循环直到 batch-selector 返回空

设计文档：§5.2 调度逻辑
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional

from .kanban_task_creator import create_dependency_chain, save_tasks_to_kanban


def check_task_completion(task_name: str, kanban_file: str) -> bool:
    """
    检查 task 是否完成

    Args:
        task_name: task 名称
        kanban_file: Kanban 文件路径

    Returns:
        True: task 已完成
        False: task 未完成
    """
    if not Path(kanban_file).exists():
        return False

    with open(kanban_file) as f:
        for line in f:
            task = json.loads(line)
            if task.get("task_name") == task_name:
                return task.get("status") == "completed"

    return False


def orchestrator_loop(
    manifest_path: str,
    run_dir: str,
    kanban_file: str,
    max_rounds: int = 100,
) -> Dict:
    """
    Kanban 调度循环

    Args:
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径
        kanban_file: Kanban 文件路径
        max_rounds: 最大轮次（防止无限循环）

    Returns:
        result: {
            "status": "completed",
            "total_rounds": N,
            "total_tests": M,
            "pass_rate": X,
        }
    """
    current_round = 1

    while current_round <= max_rounds:
        # Step 1: 等待 batch-selector task 完成
        batch_selector_task = f"batch-selector-round-{current_round}"

        # Polling 等待（简化实现，实际应使用 Hermes webhook）
        while not check_task_completion(batch_selector_task, kanban_file):
            time.sleep(5)  # 5秒 polling间隔

        # Step 2: 读取 batch-selector 结果
        batch_config_path = f"{run_dir}/batch_config.json"
        batch_result = json.loads(Path(batch_config_path).read_text())

        # Step 3: 创建依赖链
        dependency_chain = create_dependency_chain(
            batch_result, manifest_path, run_dir, current_round
        )

        # Step 4: 检查循环终止条件
        if dependency_chain is None:
            # batch-selector 返回空，循环终止
            manifest = json.loads(Path(manifest_path).read_text())
            stats = manifest.get("statistics", {})

            return {
                "status": "completed",
                "total_rounds": current_round,
                "total_tests": stats.get("total", 0),
                "pass_rate": stats.get("pass_rate", 0),
            }

        # Step 5: 提交依赖链到 Kanban
        save_tasks_to_kanban(dependency_chain, kanban_file)

        # Step 6: 进入下一轮
        current_round += 1

    # 达到 max_rounds，返回异常
    return {
        "status": "max_rounds_exceeded",
        "total_rounds": current_round,
        "reason": f"Reached max_rounds limit ({max_rounds})",
    }


# 测试入口（手动验证）
if __name__ == "__main__":
    manifest_path = "tests/ut/integration/fixtures/test_manifest.json"
    run_dir = "tests/ut/integration/fixtures/run_dir"
    kanban_file = "tests/ut/integration/fixtures/kanban_tasks.jsonl"

    # 清空 kanban_file
    Path(kanban_file).write_text("")

    # 运行调度循环（需要模拟 batch-selector 完成）
    result = orchestrator_loop(manifest_path, run_dir, kanban_file, max_rounds=3)
    print(f"Orchestrator result: {json.dumps(result, indent=2)}")