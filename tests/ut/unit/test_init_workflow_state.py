"""Tests for init_workflow_state.py — schema-valid init + loud failure.

Regression coverage for the "silent early-return" bug: with a frozen (or any)
config, create_initial_state built workflow.status='initialized', which the v5
schema rejects (see test_state_schema_v5.test_workflow_status_initialized_rejected).
validate_and_write then failed, create_initial_state returned an {"error": ...}
dict, main() ignored it, and the process exited 0 WITHOUT writing
current_run.json — so a fresh run silently reused the stale run_dir.

Two guarantees:
  1. create_initial_state produces a schema-valid state and writes the pointer.
  2. main() exits non-zero when create_initial_state reports an error, so a
     validation failure can never again masquerade as success (EXIT=0).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INIT_SCRIPT = PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "init_workflow_state.py"

from skills.ut.ut_common.validate_schema import validate_state


@pytest.fixture(scope="module")
def initmod():
    """Import init_workflow_state.py by file path."""
    sys.path.insert(0, str(INIT_SCRIPT.parent))
    sys.path.insert(0, str(INIT_SCRIPT.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("init_workflow_state", INIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_minimal_config(tmp_path: Path) -> Path:
    """Write a minimal workflow.yaml + test_list in an isolated tmp workspace."""
    test_list = tmp_path / "test_list.txt"
    test_list.write_text("tests/foo.py::test_a\ntests/foo.py::test_b\n", encoding="utf-8")

    yaml_path = tmp_path / "workflow.yaml"
    yaml_path.write_text(
        "workflow:\n"
        "  name: UT Test Workflow\n"
        '  version: "2.2"\n'
        '  test_name: "ut"\n'
        "config:\n"
        f'  workspace: "{tmp_path.as_posix()}"\n'
        f'  runs_dir: "{(tmp_path / "runs").as_posix()}"\n'
        "input_filter:\n"
        f'  test_list_path: "{test_list.as_posix()}"\n',
        encoding="utf-8",
    )
    return yaml_path


def test_init_produces_schema_valid_state_and_writes_pointer(initmod, tmp_path, monkeypatch):
    """Root cause: a freshly-initialized state must validate AND write the pointer."""
    # Pin agents_dir (current_run.json home) into the isolated tmp workspace.
    monkeypatch.setattr(initmod, "_project_root", tmp_path)
    yaml_path = _write_minimal_config(tmp_path)

    state = initmod.create_initial_state(yaml_path)

    # Must not have silently returned the error sentinel.
    assert "error" not in state, state
    # Must be schema-valid (this is what was failing: status='initialized').
    validate_state(state)

    # Pointer must be written to the canonical .agents/current_run.json.
    pointer_file = tmp_path / ".agents" / "current_run.json"
    assert pointer_file.exists(), "current_run.json pointer was not written"
    pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
    assert pointer["run_dir"] == state["paths"]["run_dir"]


def test_main_exits_nonzero_on_validation_failure(initmod, tmp_path, monkeypatch):
    """Defense-in-depth: a validation failure must surface as EXIT!=0, never EXIT=0."""
    yaml_path = _write_minimal_config(tmp_path)

    def _fake_create(*args, **kwargs):
        return {"error": "schema_validation_failed", "details": ["boom"]}

    monkeypatch.setattr(initmod, "create_initial_state", _fake_create)
    monkeypatch.setattr(sys, "argv", ["init_workflow_state.py", "--workflow-yaml", str(yaml_path)])

    with pytest.raises(SystemExit) as exc:
        initmod.main()
    assert exc.value.code != 0
