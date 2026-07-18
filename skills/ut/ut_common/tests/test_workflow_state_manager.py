#!/usr/bin/env python3
"""workflow_state_manager.py 基础测试

测试核心状态管理逻辑，确保：
- 状态转换正确性（generated → running → completed）
- 文件不存在处理
- JSON格式错误处理
- 统计计算准确性
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

# Import the module to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / "skills/ut/ut_common"))
from workflow_state_manager import (
    load_workflow_state,
    save_workflow_state,
    update_batch_generated,
    update_batch_running,
    update_batch_completed,
    calculate_batch_stats,
    calculate_test_stats
)


class TestWorkflowStateManager:
    """测试 workflow_state_manager 核心功能"""

    def setup_method(self):
        """每个测试方法前创建临时目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.workflow_state_path = Path(self.temp_dir) / "workflow_state.json"

        # 创建初始workflow_state
        initial_state = {
            "workflow": {
                "name": "UT Test Workflow",
                "version": "2.3",
                "test_name": "ut",
                "started_at": datetime.now().isoformat(),
                "status": "running"
            },
            "paths": {
                "manifest": "manifest.json",
                "batches_dir": "batches"
            },
            "batches": {},
            "test_stats": {},
            "batch_stats": {}
        }
        save_workflow_state(initial_state, self.workflow_state_path)

    def teardown_method(self):
        """每个测试方法后清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # === Critical: 状态转换正确性 ===

    def test_state_transition_generated_to_running_to_completed(self):
        """测试完整状态转换链：generated → running → completed"""
        batch_id = "batch_20260703_093155"

        # Step 1: generated
        update_batch_generated(
            workflow_state_path=self.workflow_state_path,
            batch_id=batch_id,
            batch_size=8,
            config_path=f"batches/{batch_id}/batch_config.json",
            created_at=datetime.now().isoformat()
        )

        state = load_workflow_state(self.workflow_state_path)
        assert state["batches"][batch_id]["status"] == "generated"
        assert state["batch_stats"]["generated"] == 1

        # Step 2: running
        update_batch_running(
            workflow_state_path=self.workflow_state_path,
            batch_id=batch_id,
            gpu_pool=[0, 1],
            started_at=datetime.now().isoformat()
        )

        state = load_workflow_state(self.workflow_state_path)
        assert state["batches"][batch_id]["status"] == "running"
        assert state["batch_stats"]["running"] == 1
        assert state["batch_stats"]["generated"] == 0

        # Step 3: completed
        update_batch_completed(
            workflow_state_path=self.workflow_state_path,
            batch_id=batch_id,
            results_path=f"batches/{batch_id}/batch_results.json",
            stats={"total": 8, "passed": 7, "failed": 1, "error": 0, "ignored": 0},
            completed_at=datetime.now().isoformat()
        )

        state = load_workflow_state(self.workflow_state_path)
        assert state["batches"][batch_id]["status"] == "completed"
        assert state["batch_stats"]["completed"] == 1
        assert state["batch_stats"]["running"] == 0
        assert state["test_stats"]["passed"] == 7
        assert state["test_stats"]["failed"] == 1

    def test_multiple_batches_statistics(self):
        """测试多个batch的统计计算准确性"""
        # Create 3 batches
        for i in range(3):
            batch_id = f"batch_{i}"
            update_batch_generated(
                workflow_state_path=self.workflow_state_path,
                batch_id=batch_id,
                batch_size=8,
                config_path=f"batches/{batch_id}/config.json",
                created_at=datetime.now().isoformat()
            )

        state = load_workflow_state(self.workflow_state_path)
        assert state["batch_stats"]["generated"] == 3

        # Complete 2 batches
        for i in range(2):
            batch_id = f"batch_{i}"
            update_batch_running(
                workflow_state_path=self.workflow_state_path,
                batch_id=batch_id,
                gpu_pool=[0],
                started_at=datetime.now().isoformat()
            )
            update_batch_completed(
                workflow_state_path=self.workflow_state_path,
                batch_id=batch_id,
                results_path=f"batches/{batch_id}/results.json",
                stats={"total": 8, "passed": 6, "failed": 2, "error": 0, "ignored": 0},
                completed_at=datetime.now().isoformat()
            )

        state = load_workflow_state(self.workflow_state_path)
        assert state["batch_stats"]["generated"] == 1  # 1 still generated
        assert state["batch_stats"]["completed"] == 2  # 2 completed
        assert state["test_stats"]["passed"] == 12     # 6 * 2
        assert state["test_stats"]["failed"] == 4      # 2 * 2

    # === Critical: 错误处理 ===

    def test_missing_file_raises_error(self):
        """测试文件不存在时抛出FileNotFoundError"""
        non_existent_path = Path(self.temp_dir) / "nonexistent.json"

        with pytest.raises(FileNotFoundError) as exc_info:
            load_workflow_state(non_existent_path)

        assert "workflow_state.json 不存在" in str(exc_info.value)

    def test_corrupted_json_raises_error(self):
        """测试JSON格式错误时抛出ValueError"""
        corrupted_path = Path(self.temp_dir) / "corrupted.json"
        corrupted_path.write_text("{ invalid json }")

        with pytest.raises(ValueError) as exc_info:
            load_workflow_state(corrupted_path)

        assert "workflow_state.json 格式错误" in str(exc_info.value)

    def test_update_nonexistent_batch_raises_error(self):
        """测试更新不存在的batch时抛出ValueError"""
        batch_id = "nonexistent_batch"

        with pytest.raises(ValueError) as exc_info:
            update_batch_running(
                workflow_state_path=self.workflow_state_path,
                batch_id=batch_id,
                gpu_pool=[0],
                started_at=datetime.now().isoformat()
            )

        assert "batch_id 不存在" in str(exc_info.value)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])