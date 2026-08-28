#!/usr/bin/env python3
"""Tests for workflow_state_manager.calculate_resume_info."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "skills" / "ut" / "ut_common"))

from workflow_state_manager import calculate_resume_info


def _mk_batches(statuses: dict) -> dict:
    """Build batches dict from {batch_id: status}."""
    return {
        bid: {"status": st, "created_at": f"2026-07-19T{i:06d}"}
        for i, (bid, st) in enumerate(statuses.items())
    }


class TestCalculateResumeInfo:
    def test_empty_batches(self):
        info = calculate_resume_info({}, {})
        assert info["pending_batches_count"] == 0
        assert info["can_resume"] is False
        assert info["last_batch_id"] is None

    def test_all_completed_pending_zero(self):
        batches = _mk_batches({f"batch_{i}": "completed" for i in range(10)})
        info = calculate_resume_info(batches, {"generated": 10, "completed": 10})
        assert info["pending_batches_count"] == 0
        assert info["last_batch_status"] == "completed"
        assert info["resume_recommendation"] == "生成新batch继续执行"

    def test_one_generated_pending_one(self):
        # 回归: 旧实现 generated(1) - completed(1409) = -1408 负数
        batches = _mk_batches(
            {f"batch_{i}": "completed" for i in range(1409)}
        )
        batches["batch_last"] = {
            "status": "generated", "created_at": "2026-07-19T22:10:23",
        }
        info = calculate_resume_info(
            batches, {"generated": 1, "completed": 1409}
        )
        assert info["pending_batches_count"] == 1  # 不是 -1408
        assert info["last_batch_id"] == "batch_last"
        assert info["last_batch_status"] == "generated"
        assert info["resume_recommendation"] == "执行最近生成的batch"

    def test_running_batch_pending_counts(self):
        batches = _mk_batches(
            {"b1": "completed", "b2": "generated", "b3": "running"}
        )
        info = calculate_resume_info(batches, {"generated": 1, "running": 1, "completed": 1})
        assert info["pending_batches_count"] == 2  # generated + running
        assert info["resume_recommendation"] == "继续执行当前running batch，或检查是否需要重新执行"

    def test_mixed_statuses_ignores_completed_and_failed(self):
        batches = _mk_batches(
            {"b1": "completed", "b2": "failed", "b3": "generated", "b4": "aborted"}
        )
        info = calculate_resume_info(batches, {"generated": 1, "completed": 1})
        assert info["pending_batches_count"] == 1  # 只有 generated
