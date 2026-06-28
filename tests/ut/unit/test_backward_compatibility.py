"""
test_backward_compatibility.py - Verify backward compatibility with old executor versions.

Tests that batch_results.json without dependency_classification field (from old executor)
is still valid after schema update (Task 1: field is optional).
"""

import json
from pathlib import Path
import pytest
from jsonschema import validate


_SCRIPT_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = _SCRIPT_DIR.parent.parent.parent / "skills" / "ut" / "unit-test-executor" / "batch_results_schema.json"


def _load_schema():
    """Read the canonical batch_results_schema.json."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_backward_compatibility_old_executor():
    """Old executor without dependency_classification field still valid"""
    schema = _load_schema()

    # Mock old executor result (no dependency_classification field)
    mock_old_executor_result = {
        "batch_id": "batch_old",
        "started_at": "2026-06-28T10:00:00Z",
        "finished_at": "2026-06-28T10:05:00Z",
        "exit_code": 0,
        "remote_log": {
            "host": "t_h20",
            "container": "v0.13.0",
            "raw_log_path": "/gpfs/pytest_batch_old.log",  # Match schema pattern
            "size_bytes": 1024,
            "captured_at": "2026-06-28T10:05:00Z"
        },
        "tests": [
            {
                "id": 1,
                "test_node": "tests/test_example.py::test_example",
                "status": "passed",
                "error_type": None,
                "error_message": None,
                "duration_ms": 1000,
                "exit_code": 0
                # No dependency_classification field - old executor behavior
            }
        ],
        "statistics": {
            "total": 1,
            "passed": 1,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "retriable_error": 0,
            "ignored": 0
        }
    }

    # Should pass - dependency_classification is optional (backward compatible)
    validate(mock_old_executor_result, schema)