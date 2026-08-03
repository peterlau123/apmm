#!/usr/bin/env python3
"""workflow_state.json 状态管理工具函数

提供统一的 workflow_state.json 更新接口，确保：
- 每次更新自动计算 batch_stats, test_stats, resume_info
- 强制校验必需字段
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import os

# Clear PYTHONPATH to avoid Hermes venv leaking
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']


def load_workflow_state(workflow_state_path: Path) -> dict:
    """加载 workflow_state.json，校验必需字段"""
    if not workflow_state_path.exists():
        raise FileNotFoundError(f"workflow_state.json 不存在: {workflow_state_path}")

    content = workflow_state_path.read_text(encoding="utf-8")
    try:
        state = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"workflow_state.json 格式错误: {e}")

    # 确保必需字段存在
    required_fields = ["workflow", "paths", "batches", "test_stats", "batch_stats"]
    for field in required_fields:
        if field not in state:
            if field == "workflow":
                state[field] = {"name": "UT Test Workflow", "version": "2.3", "test_name": "ut", "started_at": datetime.now().isoformat(), "status": "running"}
            else:
                state[field] = {}

    return state


def save_workflow_state(state: dict, workflow_state_path: Path) -> None:
    """保存 workflow_state.json"""
    state["last_update"] = datetime.now().isoformat()
    workflow_state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def calculate_batch_stats(batches: dict) -> dict:
    """统计 batch 数量"""
    stats = {"generated": 0, "running": 0, "completed": 0, "failed": 0}
    for batch_id, batch_info in batches.items():
        status = batch_info.get("status", "generated")
        stats[status] = stats.get(status, 0) + 1

    stats["total_tests_executed"] = sum(
        batch_info.get("stats", {}).get("passed", 0) +
        batch_info.get("stats", {}).get("failed", 0) +
        batch_info.get("stats", {}).get("error", 0) +
        batch_info.get("stats", {}).get("ignored", 0)
        for batch_info in batches.values()
        if batch_info.get("status") == "completed"
    )
    return stats


def calculate_test_stats(batches: dict, test_load_stats: dict = None) -> dict:
    """统计 test 数量"""
    stats = {"passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 0}
    for batch_info in batches.values():
        if batch_info.get("status") == "completed":
            batch_stats = batch_info.get("stats", {})
            stats["passed"] += batch_stats.get("passed", 0)
            stats["failed"] += batch_stats.get("failed", 0)
            stats["error"] += batch_stats.get("error", 0)
            stats["ignored"] += batch_stats.get("ignored", 0)

    if test_load_stats:
        stats["pending"] = test_load_stats.get("pending", 0)
        stats["total_tests"] = test_load_stats.get("total_tests", 0)
    return stats


def calculate_resume_info(batches: dict, batch_stats: dict) -> dict:
    """计算 resume 信息和建议"""
    if not batches:
        return {"last_batch_id": None, "last_batch_status": None, "pending_batches_count": 0, "can_resume": False, "resume_recommendation": "无batch记录，需要重新生成"}

    last_batch_id = max(batches.keys(), key=lambda k: batches[k].get("created_at", ""))
    last_batch = batches[last_batch_id]
    can_resume = last_batch.get("status") in ("generated", "running", "completed")
    # pending = 仍处于 generated/running 的 batch 数（基于实际状态, 而非增量计数）
    # 旧实现用 batch_stats 增量计数相减: generated - completed - running,
    # 但 generated 是"生成时+1"的增量, completed 是累计数, 口径不一致 -> 负数。
    pending = sum(
        1 for b in batches.values()
        if b.get("status") in ("generated", "running")
    )

    if last_batch.get("status") == "running":
        recommendation = "继续执行当前running batch，或检查是否需要重新执行"
    elif last_batch.get("status") == "generated":
        recommendation = "执行最近生成的batch"
    else:
        recommendation = "生成新batch继续执行"

    return {"last_batch_id": last_batch_id, "last_batch_status": last_batch.get("status"), "pending_batches_count": pending, "can_resume": can_resume, "resume_recommendation": recommendation}


def update_batch_generated(workflow_state_path: Path, batch_id: str, batch_size: int, config_path: str, created_at: str) -> None:
    """更新 batch 为 'generated' 状态"""
    state = load_workflow_state(workflow_state_path)
    if "batches" not in state:
        state["batches"] = {}

    state["batches"][batch_id] = {"status": "generated", "batch_size": batch_size, "gpu_pool": None, "created_at": created_at, "started_at": None, "completed_at": None, "config_path": config_path, "results_path": None, "stats": None}
    state["batch_stats"] = calculate_batch_stats(state["batches"])
    state["resume_info"] = calculate_resume_info(state["batches"], state["batch_stats"])
    state["current_batch"] = {"batch_id": batch_id, "size": batch_size, "started_at": None}
    save_workflow_state(state, workflow_state_path)


def update_batch_running(workflow_state_path: Path, batch_id: str, gpu_pool: list, started_at: str) -> None:
    """更新 batch 为 'running' 状态"""
    state = load_workflow_state(workflow_state_path)
    if batch_id not in state.get("batches", {}):
        raise ValueError(f"batch_id 不存在: {batch_id}")

    state["batches"][batch_id]["status"] = "running"
    state["batches"][batch_id]["gpu_pool"] = gpu_pool
    state["batches"][batch_id]["started_at"] = started_at
    state["batch_stats"] = calculate_batch_stats(state["batches"])
    state["resume_info"] = calculate_resume_info(state["batches"], state["batch_stats"])
    state["current_batch"]["started_at"] = started_at
    save_workflow_state(state, workflow_state_path)


def update_batch_completed(workflow_state_path: Path, batch_id: str, results_path: str, stats: dict, completed_at: str) -> None:
    """更新 batch 为 'completed' 状态"""
    state = load_workflow_state(workflow_state_path)
    if batch_id not in state.get("batches", {}):
        raise ValueError(f"batch_id 不存在: {batch_id}")

    state["batches"][batch_id]["status"] = "completed"
    state["batches"][batch_id]["results_path"] = results_path
    state["batches"][batch_id]["stats"] = stats
    state["batches"][batch_id]["completed_at"] = completed_at
    state["batch_stats"] = calculate_batch_stats(state["batches"])
    state["test_stats"] = calculate_test_stats(state["batches"], state.get("test_stats"))
    state["resume_info"] = calculate_resume_info(state["batches"], state["batch_stats"])
    save_workflow_state(state, workflow_state_path)