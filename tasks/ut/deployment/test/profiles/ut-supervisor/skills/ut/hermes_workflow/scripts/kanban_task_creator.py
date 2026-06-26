"""
Kanban Task Creator - 创建 Kanban task + 依赖链

职责：
1. Supervisor 创建第一个 batch-selector task（启动流程）
2. batch-selector 完成后创建后续依赖链（executor → fixer → manifest-updater → next batch-selector）
3. batch-selector 返回空时终止循环

设计文档：§5.1 任务依赖链
"""

import json
from pathlib import Path
from typing import Dict, List, Optional


def create_initial_task(manifest_path: str, run_dir: str) -> Dict:
    """
    Supervisor 创建第一个 batch-selector task

    Args:
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径

    Returns:
        task_config: Kanban task 配置
    """
    manifest = json.loads(Path(manifest_path).read_text())

    # 检查是否有 pending 测试
    pending_tests = [t for t in manifest["tests"] if t["status"] == "pending"]
    if not pending_tests:
        return {"status": "empty", "reason": "no pending tests"}

    # 创建 batch-selector task
    task_config = {
        "task_name": "batch-selector-round-1",
        "profile": "ut-batch-selector",
        "context": {
            "manifest_path": manifest_path,
            "run_dir": run_dir,
            "round": 1,
        },
        "parents": [],  # 第一个 task 无依赖
    }

    return task_config


def create_dependency_chain(
    batch_result: Dict,
    manifest_path: str,
    run_dir: str,
    current_round: int,
) -> Optional[List[Dict]]:
    """
    batch-selector 完成后创建后续依赖链

    Args:
        batch_result: batch-selector 返回结果（batch_config.json）
        manifest_path: manifest.json 路径
        run_dir: 运行目录路径
        current_round: 当前轮次

    Returns:
        dependency_chain: executor → fixer → manifest-updater → next batch-selector
        None: 如果 batch-selector 返回空（循环终止）
    """
    # 检查 batch 是否为空
    if batch_result.get("status") == "empty":
        return None  # 循环终止，不发飞书（Supervisor 监控会处理）

    # 创建依赖链
    executor_task = {
        "task_name": f"executor-round-{current_round}",
        "profile": "ut-executor",
        "context": {
            "batch_config_path": f"{run_dir}/batch_config.json",
            "run_dir": run_dir,
        },
        "parents": [f"batch-selector-round-{current_round}"],
    }

    fixer_task = {
        "task_name": f"fixer-round-{current_round}",
        "profile": "ut-fixer",
        "context": {
            "batch_results_path": f"{run_dir}/batch_results.json",
            "manifest_path": manifest_path,
            "run_dir": run_dir,
        },
        "parents": [f"executor-round-{current_round}"],
    }

    manifest_updater_task = {
        "task_name": f"manifest-updater-round-{current_round}",
        "profile": "ut-manifest-updater",
        "context": {
            "batch_results_path": f"{run_dir}/batch_results.json",
            "handled_tests_path": f"{run_dir}/handled_tests.json",
            "manifest_path": manifest_path,
            "run_dir": run_dir,
        },
        "parents": [f"fixer-round-{current_round}"],
    }

    # 创建 next batch-selector task（下一轮）
    next_batch_selector_task = {
        "task_name": f"batch-selector-round-{current_round + 1}",
        "profile": "ut-batch-selector",
        "context": {
            "manifest_path": manifest_path,
            "run_dir": run_dir,
            "round": current_round + 1,
        },
        "parents": [f"manifest-updater-round-{current_round}"],
    }

    return [executor_task, fixer_task, manifest_updater_task, next_batch_selector_task]


def save_tasks_to_kanban(tasks: List[Dict], kanban_file: str) -> None:
    """
    保存 tasks 到 Kanban 文件（JSON Lines）

    Args:
        tasks: task 配置列表
        kanban_file: Kanban 文件路径
    """
    with open(kanban_file, "a") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")


# 测试入口（手动验证）
if __name__ == "__main__":
    # 测试 create_initial_task
    manifest_path = "tests/ut/integration/fixtures/test_manifest.json"
    run_dir = "tests/ut/integration/fixtures/run_dir"

    task = create_initial_task(manifest_path, run_dir)
    print(f"Initial task: {json.dumps(task, indent=2)}")

    # 测试 create_dependency_chain
    batch_result = {"status": "non_empty", "batch_id": "batch-001"}
    chain = create_dependency_chain(batch_result, manifest_path, run_dir, 1)
    if chain:
        print(f"Dependency chain: {json.dumps(chain, indent=2)}")
    else:
        print("Loop terminated (batch empty)")