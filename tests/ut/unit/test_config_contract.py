"""Task 0.1: single config contract (G1/G2).

get_execute_config flattens the nested workflow_state config into the flat
keys execute_batch expects. Loaded by file path (hyphenated skill dirs).
"""
import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERMES_RUNNER = PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "hermes_runner.py"


def _load_hermes_runner():
    sys.path.insert(0, str(HERMES_RUNNER.parent))
    sys.path.insert(0, str(HERMES_RUNNER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("hermes_runner", HERMES_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_get_execute_config_flattens_nested(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"config": {
        "remote": {"server": "t_h20", "docker": "v0.13.0_torch2.5.1_compile",
                   "vllm_dir": "/gpfs/gcsp/M2.7_verify/vllm"},
        "batch_size": 8, "timeout": 600, "pytest_args": "-v --tb=long"}}))
    hr = _load_hermes_runner()
    cfg = hr.get_execute_config(state_path)
    assert cfg["remote_server"] == "t_h20"
    assert cfg["docker_container"] == "v0.13.0_torch2.5.1_compile"
    assert cfg["timeout"] == 600
    assert cfg["pytest_args"] == "-v --tb=long"
    assert cfg["remote_log_dir"].endswith("/ut_logs")


def test_get_execute_config_uses_defaults_when_config_empty(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"config": {}}))
    hr = _load_hermes_runner()
    cfg = hr.get_execute_config(state_path)
    assert cfg["remote_server"] == "t_h20"
    assert cfg["docker_container"] == "v0.13.0_torch2.5.1_compile"
    assert cfg["timeout"] == 600
    assert cfg["pytest_args"] == "-v --tb=long"
    assert cfg["remote_log_dir"] == "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"
