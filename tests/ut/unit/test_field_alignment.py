"""Task 0.3 / Gap G4: execute_batch must accept test dicts that use the
`test_id` field emitted by the batch selector, not only `test_node`.

The executor scripts live under skills/ut/unit-test-executor/scripts/ which is a
hyphenated directory (not a Python package). We load the modules by file path
via importlib, mirroring tests/skills/ut/test_execute_batch_v5.py.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_DIR = REPO_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


execute_batch_mod = _load("ut_executor_execute_batch", "execute_batch.py")


def test_execute_batch_accepts_test_id_field(tmp_path):
    batch_dir = tmp_path / "batch_x"
    batch_dir.mkdir()
    cfg = {
        "batch_id": "batch_x",
        "iteration": 1,
        "run_id": "ut",
        "tests": [
            {"test_id": "tests/test_a.py::test_x", "selected_reason": "pending"},
        ],
    }
    (batch_dir / "batch_config.json").write_text(json.dumps(cfg), encoding="utf-8")

    exec_config = {
        "remote_server": "t_h20",
        "docker_container": "v0.13.0_torch2.5.1_compile",
        "remote_log_dir": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
    }

    summary_text = (
        "PASSED tests/test_a.py::test_x\n"
        "===== 1 passed in 0.42s =====\n"
    )

    def fake_run_remote(cmd, *, timeout=None, **kwargs):
        if "pytest" in cmd:
            return {"exit_code": 0, "stdout": "", "stderr": "", "size_bytes": 1234}
        # grep + tail extraction
        return {"exit_code": 0, "stdout": summary_text, "stderr": ""}

    cfg_path = batch_dir / "batch_config.json"
    state_path = tmp_path / "workflow_state.json"  # unused: exec_config injected

    with mock.patch.object(execute_batch_mod, "run_remote", side_effect=fake_run_remote):
        result = execute_batch_mod.execute_batch(
            cfg_path, state_path, exec_config=exec_config
        )

    # No KeyError('test_node') was raised, and the results file was written.
    results_path = batch_dir / "batch_results.json"
    assert results_path.exists()

    out = json.loads(results_path.read_text(encoding="utf-8"))
    assert out["tests"][0]["test_node"] == "tests/test_a.py::test_x"
    assert out["statistics"]["total"] == 1
