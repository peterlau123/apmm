"""test_batch_id_forwarding.py - Test batch_id forwarding in generate_batch.py."""
import json, sys
from pathlib import Path
import pytest
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "skills" / "ut" / "batch-selector" / "scripts" / "generate_batch.py"
@pytest.fixture(scope="module")
def generate_batch_mod():
    import importlib.util
    sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("generate_batch", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
def _make_test_load(tmp_path):
    tl = {"version": "2.0", "tests": [
        {"id": 1, "test_node": "tests/test_a.py::test_one", "test_file": "tests/test_a.py", "test_name": "test_one", "status": "pending"},
        {"id": 2, "test_node": "tests/test_b.py::test_two", "test_file": "tests/test_b.py", "test_name": "test_two", "status": "pending"}]}
    tl_path = tmp_path / "test_load_2.json"
    tl_path.write_text(json.dumps(tl), encoding="utf-8")
    return tl_path
def _make_workflow_state(tmp_path, test_load_path):
    state = {"workflow": {"name": "UT", "version": "2.0", "test_name": "ut", "started_at": "2026-07-17T00:00:00Z", "status": "running"},
             "current_stage": "select_batch", "iteration": 0,
             "paths": {"run_dir": str(tmp_path), "test_load": str(test_load_path), "batches_dir": str(tmp_path / "batches")},
             "stats": {"total_tests": 2, "passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 2, "error_rate": 0.0},
             "current_batch": {"batch_id": None, "size": 0, "started_at": None},
             "flags": {"stop_requested": False, "pause_requested": False, "pause_reason": None, "consecutive_failures": 0},
             "last_update": "2026-07-17T00:00:00Z"}
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path
class TestBatchIdForwarding:
    def test_explicit_batch_id_is_used(self, tmp_path, generate_batch_mod):
        tl_path = _make_test_load(tmp_path)
        state_path = _make_workflow_state(tmp_path, tl_path)
        batches_dir = tmp_path / "batches"; batches_dir.mkdir()
        result = generate_batch_mod.generate_batch_from_workflow_state(
            workflow_state_path=state_path, batch_dir=batches_dir, batch_size=8, batch_id="my_custom_id_001")
        assert result["batch_id"] == "my_custom_id_001"
        cfg = json.loads(Path(result["batch_config_path"]).read_text(encoding="utf-8"))
        assert cfg["batch_id"] == "my_custom_id_001"
    def test_none_batch_id_auto_generates(self, tmp_path, generate_batch_mod):
        tl_path = _make_test_load(tmp_path)
        state_path = _make_workflow_state(tmp_path, tl_path)
        batches_dir = tmp_path / "batches"; batches_dir.mkdir()
        result = generate_batch_mod.generate_batch_from_workflow_state(
            workflow_state_path=state_path, batch_dir=batches_dir, batch_size=8, batch_id=None)
        assert result["batch_id"] is not None
        assert result["batch_id"].startswith("batch_")
    def test_batch_id_in_directory_name(self, tmp_path, generate_batch_mod):
        tl_path = _make_test_load(tmp_path)
        state_path = _make_workflow_state(tmp_path, tl_path)
        batches_dir = tmp_path / "batches"; batches_dir.mkdir()
        result = generate_batch_mod.generate_batch_from_workflow_state(
            workflow_state_path=state_path, batch_dir=batches_dir, batch_size=8, batch_id="batch_dir_test_42")
        assert Path(result["batch_dir"]).name == "batch_dir_test_42"
