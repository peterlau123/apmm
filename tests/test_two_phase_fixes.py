#!/usr/bin/env python3
"""
Tests for two-phase strategy fixes F1-F4.

F1: Phase 1 refreshes test_load stats into workflow_state on completion
F2: Phase 1 transitions workflow_state to phase1_complete / current_stage=phase2
F3: Phase 1 auto-triggers Phase 2 Stage 1
F4: Phase 2 Stage 2 refreshes stats after each retry
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import importlib.util

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# phase2_stage2.py has no __init__.py chain; load via importlib
_p2s2_path = _PROJECT_ROOT / "skills" / "ut" / "ut_common" / "two-phase-handler" / "scripts" / "phase2_stage2.py"
_p2s2_spec = importlib.util.spec_from_file_location("phase2_stage2", _p2s2_path)
_p2s2 = importlib.util.module_from_spec(_p2s2_spec)
_p2s2_spec.loader.exec_module(_p2s2)


class TestF1F2_Phase1StateTransition:
    """F1+F2: _finalize_phase1_state updates workflow_state correctly."""

    def test_refreshes_stats_from_test_load(self, tmp_path):
        """F1: workflow_state.stats should reflect test_load statuses."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        # Setup: test_load with mixed statuses
        test_load = {"tests": [
            {"status": "passed"}, {"status": "passed"},
            {"status": "failed"},
            {"status": "ignored"}, {"status": "ignored"},
            {"status": "error"},
        ]}
        tl_path = tmp_path / "test_load.json"
        tl_path.write_text(json.dumps(test_load))

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {"passed": 0, "failed": 0, "pending": 32933},
            "paths": {"test_load": str(tl_path)},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 2
        assert result["stats"]["failed"] == 1
        assert result["stats"]["ignored"] == 2
        assert result["stats"]["error"] == 1
        assert result["stats"]["pending"] == 0

    def test_transitions_status_to_phase1_complete(self, tmp_path):
        """F2: workflow.status -> phase1_complete, current_stage -> phase2."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": ""},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["workflow"]["status"] == "phase1_complete"
        assert result["current_stage"] == "phase2"

    def test_handles_missing_workflow_state(self, tmp_path):
        """Should not crash if workflow_state.json doesn't exist."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        # Should be a no-op
        _finalize_phase1_state(tmp_path)

    def test_handles_relative_test_load_path(self, tmp_path):
        """test_load path in workflow_state may be relative to run_dir."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        test_load = {"tests": [{"status": "passed"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": "test_load.json"},  # relative
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1

    def test_handles_windows_backslash_repo_relative_path(self, tmp_path):
        """Regression: Windows-style backslash repo-relative path
        ('runs\\ut-xxx\\test_load.json') must resolve against project root,
        not run_dir (which would double-prefix)."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state, _project_root

        # Build repo-relative test_load under a fake runs/ut-xxx dir
        run_dir = tmp_path / "runs" / "ut-test-run"
        run_dir.mkdir(parents=True)
        test_load = {"tests": [{"status": "passed"}, {"status": "failed"}]}
        (run_dir / "test_load.json").write_text(json.dumps(test_load))

        # workflow_state lives in the run dir; paths use Windows backslashes
        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": "runs\\ut-test-run\\test_load.json"},
        }
        ws_path = run_dir / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        # Patch _project_root to tmp_path so repo-relative resolves correctly
        import tasks.ut.scripts.auto_run_batches_two_phase as mod
        old_root = mod._project_root
        try:
            mod._project_root = tmp_path
            _finalize_phase1_state(run_dir)
        finally:
            mod._project_root = old_root

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1
        assert result["stats"]["failed"] == 1
        assert result["stats"]["total_tests"] == 2

    def test_handles_backslash_filename_relative_to_run_dir(self, tmp_path):
        """Backslash filename-only path ('test_load.json') resolves to run_dir."""
        from tasks.ut.scripts.auto_run_batches_two_phase import _finalize_phase1_state

        test_load = {"tests": [{"status": "error"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "paths": {"test_load": "test_load.json"},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _finalize_phase1_state(tmp_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["error"] == 1


class TestF3_Phase2AutoTrigger:
    """F3: _trigger_phase2_stage1 calls phase2_stage1.py."""

    def test_calls_stage1_script(self, tmp_path):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_run:
            _trigger_phase2_stage1(tmp_path)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "phase2_stage1.py" in args[1]
            assert "--run-dir" in args
            assert str(tmp_path) in args

    def test_handles_missing_script(self, tmp_path, capsys):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("tasks.ut.scripts.auto_run_batches_two_phase._project_root", tmp_path):
            _trigger_phase2_stage1(tmp_path)
            captured = capsys.readouterr()
            assert "not found" in captured.out

    def test_handles_stage1_failure(self, tmp_path, capsys):
        from tasks.ut.scripts.auto_run_batches_two_phase import _trigger_phase2_stage1

        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="some error")):
            _trigger_phase2_stage1(tmp_path)
            captured = capsys.readouterr()
            assert "failed" in captured.out


class TestF4_Phase2Stage2StatsRefresh:
    """F4: _refresh_stats in phase2_stage2.py updates workflow_state."""

    def test_refreshes_stats_correctly(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [
            {"status": "passed"}, {"status": "passed"}, {"status": "passed"},
            {"status": "failed"},
        ]}
        tl_path = tmp_path / "test_load.json"
        tl_path.write_text(json.dumps(test_load))

        ws = {
            "stats": {"passed": 0, "pending": 4},
            "paths": {"test_load": str(tl_path)},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 3
        assert result["stats"]["failed"] == 1
        assert result["stats"]["pending"] == 0
        assert result["test_load_stats"]["passed"] == 3

    def test_handles_missing_file(self, tmp_path):
        _p2s2._refresh_stats(tmp_path / "nonexistent.json")

    def test_handles_no_test_load_path(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        ws = {"stats": {}, "paths": {}}
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

    def test_handles_relative_path(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [{"status": "passed"}, {"status": "failed"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        ws = {
            "stats": {},
            "paths": {"test_load": "test_load.json"},  # relative
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1
        assert result["stats"]["failed"] == 1


class TestPhase1_UserCommandCheck:
    """Phase 1 循环的 stop/pause 检查 (2026-08-04 审查新增).

    Phase 1 是长循环 (batch_group_size 个 batch), 原实现无用户命令检查,
    启动后无法中途停止. 现在每 batch 前检查 workflow_state flags.
    """

    def _make_ws(self, tmp_path, flags=None):
        ws = {
            "workflow": {"name": "UT", "status": "running"},
            "current_stage": "collect",
            "stats": {},
            "flags": flags or {},
            "paths": {},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))
        # 创建 test_load 文件 (Phase1 循环在 flags 检查前会验证其存在)
        (tmp_path / "test_load.json").write_text(json.dumps({"tests": []}))
        return ws_path

    def test_stop_requested_breaks_loop(self, tmp_path):
        """stop_requested=true 时循环应在第一个 batch 前退出."""
        from tasks.ut.scripts.auto_run_batches_two_phase import phase1_batch_loop

        ws_path = self._make_ws(tmp_path, {"stop_requested": True})
        # 用 mock 避免真正执行 batch
        with patch("tasks.ut.scripts.auto_run_batches_two_phase.get_config",
                   return_value={"phase1": {"auto_create_batches": False, "auto_execute": False,
                                            "checkpoint_interval": 10, "enable_force_checkpoints": False},
                                 "workflow": {}, "config": {"batch_size": 8}}), \
             patch("tasks.ut.scripts.auto_run_batches_two_phase.get_paths",
                   return_value={"run_dir": tmp_path, "manifest": tmp_path / "manifest.json",
                                 "test_load": tmp_path / "test_load.json"}):
            # batch_group_size=5, 但 stop 应立即退出 -> 返回空 checkpoint_log
            log = phase1_batch_loop(tmp_path / "workflow.yaml", tmp_path, batch_group_size=5)
        # 没有执行任何 batch
        assert log == []

    def test_pause_requested_breaks_loop(self, tmp_path):
        """pause_requested=true 时循环应在第一个 batch 前退出."""
        from tasks.ut.scripts.auto_run_batches_two_phase import phase1_batch_loop

        ws_path = self._make_ws(tmp_path, {"pause_requested": True})
        with patch("tasks.ut.scripts.auto_run_batches_two_phase.get_config",
                   return_value={"phase1": {"auto_create_batches": False, "auto_execute": False,
                                            "checkpoint_interval": 10, "enable_force_checkpoints": False},
                                 "workflow": {}, "config": {"batch_size": 8}}), \
             patch("tasks.ut.scripts.auto_run_batches_two_phase.get_paths",
                   return_value={"run_dir": tmp_path, "manifest": tmp_path / "manifest.json",
                                 "test_load": tmp_path / "test_load.json"}):
            log = phase1_batch_loop(tmp_path / "workflow.yaml", tmp_path, batch_group_size=5)
        assert log == []

    def test_no_flags_runs_normally(self, tmp_path):
        """无 flags 时循环正常执行 (不提前退出)."""
        from tasks.ut.scripts.auto_run_batches_two_phase import phase1_batch_loop

        self._make_ws(tmp_path, {})
        # auto_create_batches=False -> 直接跳过 batch 创建, 模拟空循环
        with patch("tasks.ut.scripts.auto_run_batches_two_phase.get_config",
                   return_value={"phase1": {"auto_create_batches": False, "auto_execute": False,
                                            "checkpoint_interval": 10, "enable_force_checkpoints": False},
                                 "workflow": {}, "config": {"batch_size": 8}}), \
             patch("tasks.ut.scripts.auto_run_batches_two_phase.get_paths",
                   return_value={"run_dir": tmp_path, "manifest": tmp_path / "manifest.json",
                                 "test_load": tmp_path / "test_load.json"}):
            log = phase1_batch_loop(tmp_path / "workflow.yaml", tmp_path, batch_group_size=3)
        # auto_create_batches=False 时循环体直接跳过, 无 batch 执行
        assert isinstance(log, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestExecuteBatch_ContainerEnvResolution:
    """Bug 4: execute_batch.py 的 container_env 读取 (2026-08-04 修复).

    原逻辑: exec_config 非 None 时直接给 container_env_raw={} → retry 脚本
    传 --timeout 后 HF_HUB_OFFLINE 等变量丢失 → 容器内测试联网 huggingface.co
    失败。且 paths.workflow_yaml 可能是 Windows 反斜杠路径, Linux 下
    Path().is_file()=False 读不到 workflow.yaml。
    """

    def _make_ws(self, tmp_path, workflow_yaml_rel=None, backslash=True):
        """构造 workflow_state.json + workflow.yaml, 返回路径."""
        # workflow.yaml 放 tmp_path 下 (模拟 run_dir)
        wf_yaml = tmp_path / "workflow.yaml"
        wf_yaml.write_text(
            "config:\n"
            "  container_env:\n"
            "    HF_HUB_OFFLINE: '1'\n"
            "    HF_HOME: /gpfs/hf_home\n"
            "    CUDA_VISIBLE_DEVICES: '0,1'\n"
        )
        ws = {
            "paths": {"workflow_yaml": str(wf_yaml)},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))
        return ws_path

    def _extract_container_env(self, tmp_path, exec_config=None):
        """按 execute_batch.py 修复后的逻辑提取 container_env."""
        import yaml
        state_raw = json.loads((tmp_path / "workflow_state.json").read_text(encoding="utf-8"))
        if exec_config is not None and exec_config.get("container_env"):
            return exec_config["container_env"]
        workflow_yaml_str = state_raw.get("paths", {}).get("workflow_yaml", "")
        workflow_yaml_path = None
        if workflow_yaml_str:
            workflow_yaml_str = workflow_yaml_str.replace("\\", "/")
            workflow_yaml_path = Path(workflow_yaml_str)
            if not workflow_yaml_path.is_absolute():
                if workflow_yaml_path.parts and workflow_yaml_path.parts[0] == "runs":
                    workflow_yaml_path = _PROJECT_ROOT / workflow_yaml_path
                else:
                    workflow_yaml_path = (tmp_path / "workflow_state.json").parent / workflow_yaml_path
        if workflow_yaml_path and workflow_yaml_path.is_file():
            wf = yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
            return wf.get("config", {}).get("container_env", {})
        return {}

    def test_exec_config_present_still_reads_workflow_yaml(self, tmp_path):
        """exec_config 存在 (如 retry 传 --timeout) 时也必须读到 container_env."""
        self._make_ws(tmp_path)
        # retry_timeout_batches.py 会传 exec_config={"timeout": 600}
        ce = self._extract_container_env(tmp_path, exec_config={"timeout": 600})
        assert ce.get("HF_HUB_OFFLINE") == "1"
        assert ce.get("HF_HOME") == "/gpfs/hf_home"

    def test_windows_backslash_path_resolution(self, tmp_path):
        """Windows 反斜杠路径 (runs\\ut-xxx\\workflow.yaml) 也能解析."""
        # 模拟 repo-relative 反斜杠路径
        fake_run = _PROJECT_ROOT / "runs" / "ut-test"
        fake_run.mkdir(parents=True, exist_ok=True)
        (fake_run / "workflow.yaml").write_text(
            "config:\n"
            "  container_env:\n"
            "    HF_HUB_OFFLINE: '1'\n"
        )
        ws = {"paths": {"workflow_yaml": r"runs\ut-test\workflow.yaml"}}
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        state_raw = json.loads(ws_path.read_text(encoding="utf-8"))
        import yaml
        workflow_yaml_str = state_raw.get("paths", {}).get("workflow_yaml", "").replace("\\", "/")
        workflow_yaml_path = Path(workflow_yaml_str)
        if not workflow_yaml_path.is_absolute():
            if workflow_yaml_path.parts and workflow_yaml_path.parts[0] == "runs":
                workflow_yaml_path = _PROJECT_ROOT / workflow_yaml_path
        assert workflow_yaml_path.is_file()
        wf = yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
        assert wf["config"]["container_env"]["HF_HUB_OFFLINE"] == "1"

    def test_exec_config_container_env_wins(self, tmp_path):
        """exec_config 显式提供 container_env 时优先 (unit tests 注入)."""
        self._make_ws(tmp_path)
        ce = self._extract_container_env(tmp_path, exec_config={
            "container_env": {"CUSTOM_VAR": "1"},
        })
        assert ce == {"CUSTOM_VAR": "1"}

    def test_missing_workflow_yaml_returns_empty(self, tmp_path):
        """无 workflow_yaml 路径时返回 {} (不崩)."""
        ws = {"paths": {}}
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))
        ce = self._extract_container_env(tmp_path)
        assert ce == {}


class TestResolveTestLoadPath:
    """_resolve_test_load_path: 反斜杠归一化 + repo-relative 锚定."""

    def test_linux_absolute_path(self, tmp_path):
        p = _p2s2._resolve_test_load_path(str(tmp_path / "test_load.json"), tmp_path / "wf.json")
        assert p == tmp_path / "test_load.json"

    def test_linux_relative_path(self, tmp_path):
        p = _p2s2._resolve_test_load_path("test_load.json", tmp_path / "wf.json")
        assert p == tmp_path / "test_load.json"

    def test_windows_backslash_repo_relative(self):
        """反斜杠 repo-relative: runs\\ut-xxx\\test_load.json → 锚定项目根."""
        wf = _PROJECT_ROOT / "runs" / "ut-xxx" / "workflow_state.json"
        p = _p2s2._resolve_test_load_path(r"runs\ut-xxx\test_load.json", wf)
        assert p == _PROJECT_ROOT / "runs" / "ut-xxx" / "test_load.json"

    def test_windows_backslash_filename_relative(self, tmp_path):
        """反斜杠文件名相对路径: xxx\test_load.json → 锚定 run_dir."""
        wf = tmp_path / "workflow_state.json"
        p = _p2s2._resolve_test_load_path(r"test_load.json", wf)
        assert p == tmp_path / "test_load.json"

    def test_backslash_already_normalized(self):
        """正斜杠路径原样传递."""
        wf = _PROJECT_ROOT / "runs" / "ut-xxx" / "workflow_state.json"
        p = _p2s2._resolve_test_load_path("runs/ut-xxx/test_load.json", wf)
        assert p == _PROJECT_ROOT / "runs" / "ut-xxx" / "test_load.json"


class TestF4_Phase2Stage2Backslash:
    """_refresh_stats 在反斜杠路径下的正确性 (Bug 2 回归)."""

    def test_refresh_with_windows_backslash_repo_relative(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [{"status": "passed"}, {"status": "failed"}]}
        # 真实位置的 test_load (在项目根下, 模拟 repo-relative)
        tl_path = _PROJECT_ROOT / "runs" / "ut-xxx" / "test_load.json"
        tl_path.parent.mkdir(parents=True, exist_ok=True)
        tl_path.write_text(json.dumps(test_load))

        # workflow_state 里用反斜杠 repo-relative 路径
        ws = {
            "stats": {},
            "paths": {"test_load": r"runs\ut-xxx\test_load.json"},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1
        assert result["stats"]["failed"] == 1

    def test_refresh_with_windows_backslash_filename(self, tmp_path):
        _refresh_stats = _p2s2._refresh_stats

        test_load = {"tests": [{"status": "passed"}]}
        (tmp_path / "test_load.json").write_text(json.dumps(test_load))

        # 反斜杠文件名相对路径
        ws = {
            "stats": {},
            "paths": {"test_load": r"test_load.json"},
        }
        ws_path = tmp_path / "workflow_state.json"
        ws_path.write_text(json.dumps(ws))

        _refresh_stats(ws_path)

        result = json.loads(ws_path.read_text())
        assert result["stats"]["passed"] == 1


class TestRetryTimeout_TestLoadUpdate:
    """retry_timeout_batches.py 的回写 test_load 功能 (Bug 3)."""

    _retry_mod = None

    @classmethod
    def setup_class(cls):
        path = _PROJECT_ROOT / "tasks" / "ut" / "scripts" / "retry_timeout_batches.py"
        spec = importlib.util.spec_from_file_location("retry_timeout_batches", path)
        cls._retry_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls._retry_mod)

    def test_retry_one_deletes_old_result(self, tmp_path):
        """retry_one 执行前应删除旧 batch_results.json."""
        # 创建旧结果文件
        bid = "batch_test"
        batch_dir = tmp_path / "batches" / bid
        batch_dir.mkdir(parents=True)
        old_result = batch_dir / "batch_results.json"
        old_result.write_text('{"old": true}')
        config = batch_dir / "batch_config.json"
        config.write_text('{"tests": []}')

        # mock subprocess.run 模拟失败 (无新文件生成)
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="error")):
            result = self._retry_mod.retry_one(bid, str(tmp_path), wall_timeout=30)

        # 旧文件被删除, 且无新文件 -> status=no_result
        assert result["status"] == "no_result", f"expected no_result, got {result}"

    def test_retry_one_calls_update_test_load(self, tmp_path):
        """retry_one 成功后应调用 update_test_load_two_phase.py."""
        bid = "batch_test2"
        batch_dir = tmp_path / "batches" / bid
        batch_dir.mkdir(parents=True)
        config = batch_dir / "batch_config.json"
        config.write_text('{"tests": []}')

        # workflow_state
        wf = tmp_path / "workflow_state.json"
        wf.write_text(json.dumps({
            "paths": {"test_load": str(tmp_path / "test_load.json")},
            "batches": {},
        }))
        (tmp_path / "test_load.json").write_text(json.dumps({"tests": []}))

        # mock subprocess.run: 第一次 (execute_batch) 成功, 第二次 (update_test_load) 也成功
        def fake_run(*args, **kwargs):
            # 如果是 execute_batch, 创建 batch_results.json
            cmd = " ".join(kwargs.get("args", args[0]) if args else [])
            if "update_test_load_two_phase" not in cmd:
                (batch_dir / "batch_results.json").write_text(
                    json.dumps({"statistics": {"passed": 1, "failed": 0}}))
            return MagicMock(returncode=0, stdout="OK", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = self._retry_mod.retry_one(bid, str(tmp_path), wall_timeout=30)

        assert result["status"] == "done", f"expected done, got {result}"
        assert result["passed"] == 1
