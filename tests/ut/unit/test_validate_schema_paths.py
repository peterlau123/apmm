"""test_validate_schema_paths.py - Test schema file locations."""
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from skills.ut.ut_common.validate_schema import SCHEMA_FILES, get_schema_path

class TestSchemaPaths:
    def test_workflow_schema_in_shared(self):
        path = get_schema_path("workflow")
        assert "shared" in str(path)
        assert "terminal-workflow" not in str(path)
        assert path.exists()

    def test_workflow_state_schema_in_shared(self):
        path = get_schema_path("workflow_state")
        assert "shared" in str(path)
        assert "terminal-workflow" not in str(path)
        assert path.exists()

    def test_no_terminal_workflow_in_paths(self):
        for name, rel_path in SCHEMA_FILES.items():
            assert "terminal-workflow" not in rel_path, f"Schema '{name}' still in terminal-workflow: {rel_path}"

    def test_all_schema_files_exist(self):
        for name in SCHEMA_FILES:
            path = get_schema_path(name)
            assert path.exists(), f"Schema '{name}' not found: {path}"
