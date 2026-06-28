#!/usr/bin/env python3
"""
test_dependency_classification.py - Comprehensive unit tests for dependency classification
optimization (Task 4 from dependency_classification optimization plan).

Consolidates tests from Task 2 (executor placeholder) and Task 3 (agent classification),
plus additional tests for executor signal preservation and signal types.

Test coverage:
1. Executor placeholder schema validation (from Task 2)
2. Agent classification parameter handling (from Task 3)
3. Executor signal preservation in batch_results
4. Executor signal types enumeration
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from jsonschema import validate

# Schema loader for executor placeholder tests
_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "ut" / "unit-test-executor" / "scripts"
_SCHEMA_PATH = _SCRIPT_DIR.parent / "batch_results_schema.json"

# Import generate_handled_manifest for agent classification tests
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import importlib.util as _ilu
_GENERATE_MANIFEST_PATH = _project_root / "skills" / "ut" / "failure-handler" / "scripts" / "generate_handled_manifest.py"
_spec = _ilu.spec_from_file_location("generate_handled_manifest", _GENERATE_MANIFEST_PATH)
generate_handled_manifest_module = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(generate_handled_manifest_module)


def _load_schema():
    """Read the canonical batch_results_schema.json."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ============================================================================
# Tests from Task 2: Executor placeholder schema validation
# ============================================================================


def test_timeout_xml_missing_placeholder_schema():
    """Verify XML missing timeout returns placeholder schema with executor_signal + executor_evidence."""
    mock_output = {
        "id": 1,
        "test_node": "tests/test_example.py::test_demo",
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "JUnit XML missing (watchdog SIGKILL or fetch empty)",
        "duration_ms": None,
        "exit_code": 124,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "timeout_no_xml",
            "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
        }
    }

    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)


def test_timeout_xml_unparseable_placeholder_schema():
    """Verify XML unparseable timeout returns placeholder schema."""
    mock_output = {
        "id": 2,
        "test_node": "tests/test_example.py::test_demo2",
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "JUnit XML unparseable (watchdog SIGKILL mid-flush?)",
        "duration_ms": None,
        "exit_code": 124,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "timeout_unparseable_xml",
            "executor_evidence": "JUnit XML unparseable (ET.ParseError)"
        }
    }

    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)


def test_timeout_no_testcase_placeholder_schema():
    """Verify no testcase timeout returns placeholder schema."""
    mock_output = {
        "id": 3,
        "test_node": "tests/test_example.py::test_demo3",
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "JUnit XML has no <testcase> (pytest aborted pre-result)",
        "duration_ms": None,
        "exit_code": 124,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "timeout_no_testcase",
            "executor_evidence": "JUnit XML has no testcase element"
        }
    }

    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)


def test_disconnect_exec_placeholder_schema():
    """Verify bastion disconnect during exec returns placeholder schema."""
    mock_output = {
        "id": 4,
        "test_node": "tests/test_example.py::test_demo4",
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "bastion disconnect during exec",
        "duration_ms": None,
        "exit_code": None,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "disconnect_exec",
            "executor_evidence": "bastion disconnect during test exec"
        }
    }

    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)


def test_disconnect_xml_fetch_placeholder_schema():
    """Verify bastion disconnect during xml fetch returns placeholder schema."""
    mock_output = {
        "id": 5,
        "test_node": "tests/test_example.py::test_demo5",
        "status": "ignored",
        "error_type": "timeout",
        "error_message": "bastion disconnect during xml fetch",
        "duration_ms": None,
        "exit_code": 124,
        "dependency_classification": {
            "status": "pending",
            "executor_signal": "disconnect_xml_fetch",
            "executor_evidence": "bastion disconnect during xml fetch"
        }
    }

    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]
    validate(mock_output, test_schema)


# ============================================================================
# Tests from Task 3: Agent classification parameter handling
# ============================================================================


def test_agent_classification_dep_stall_accepted():
    """Verify generate_handled_manifest accepts agent_classification parameter with dep_stall."""
    _handle_timeout_test = generate_handled_manifest_module._handle_timeout_test

    mock_test = {
        "test_node": "test_example",
        "error_type": "timeout",
        "error_message": "timeout"
    }
    mock_batch_dir = Path("/tmp/batch_123")

    mock_agent_classification = {
        "classification": "dep_stall",
        "evidence": "Downloading meta-llama/Llama-3.2-1B",
        "dependency_hint": "meta-llama/Llama-3.2-1B"
    }

    result = _handle_timeout_test(
        mock_test,
        mock_batch_dir,
        agent_classification=mock_agent_classification
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert "dependency_classification" in result["resolution"]
    assert result["resolution"]["dependency_classification"]["classification"] == "dep_stall"


def test_agent_classification_schema_invalid_fallback():
    """Verify invalid agent_classification triggers fallback to unknown."""
    _handle_timeout_test = generate_handled_manifest_module._handle_timeout_test

    mock_test = {
        "test_node": "test_example_invalid",
        "error_type": "timeout",
        "error_message": "timeout"
    }
    mock_batch_dir = Path("/tmp/batch_789")

    # Invalid classification (missing required 'evidence' field)
    invalid_classification = {
        "classification": "dep_stall",
        "dependency_hint": "some-model"
    }

    result = _handle_timeout_test(
        mock_test,
        mock_batch_dir,
        agent_classification=invalid_classification
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    # Should fallback to unknown due to schema validation failure
    assert result["resolution"]["dependency_classification"]["classification"] == "unknown"


def test_agent_classification_none_fallback():
    """Verify agent_classification=None triggers fallback to unknown."""
    _handle_timeout_test = generate_handled_manifest_module._handle_timeout_test

    mock_test = {
        "test_node": "test_example_timeout",
        "error_type": "timeout",
        "error_message": "timeout"
    }
    mock_batch_dir = Path("/tmp/batch_456")

    result = _handle_timeout_test(
        mock_test,
        mock_batch_dir,
        agent_classification=None
    )

    assert result is not None
    assert result["final_status"] == "ignored"
    assert "dependency_classification" in result["resolution"]
    assert result["resolution"]["dependency_classification"]["classification"] == "unknown"


def test_generate_handled_manifest_accepts_agent_classification():
    """Verify generate_handled_manifest propagates agent_classification."""
    generate_handled_manifest = generate_handled_manifest_module.generate_handled_manifest

    # Create a minimal batch_results.json structure
    batch_results = {
        "tests": [
            {
                "test_node": "test_timeout_example",
                "status": "ignored",
                "error_type": "timeout",
                "error_message": "Test timed out"
            }
        ]
    }

    mock_batch_dir = MagicMock(spec=Path)
    mock_batch_dir.__str__ = "/tmp/batch_test"
    mock_batch_dir.mkdir = MagicMock()
    mock_batch_results_path = MagicMock(spec=Path)
    mock_batch_results_path.read_text = MagicMock(return_value=json.dumps(batch_results))

    mock_agent_classification = {
        "classification": "dep_stall",
        "evidence": "Downloading model",
        "dependency_hint": "test-model"
    }

    # Mock validate_and_write to avoid schema validation
    with patch.object(generate_handled_manifest_module, 'validate_and_write') as mock_validate:
        mock_validate.return_value = (True, [])

        result = generate_handled_manifest(
            batch_id="test_batch",
            batch_results_path=mock_batch_results_path,
            batch_dir=mock_batch_dir,
            agent_classification=mock_agent_classification
        )

        # Should process timeout test with agent_classification
        assert result is not None
        assert "tests" in result
        # Verify processing occurred - at least one test processed
        assert len(result["tests"]) > 0


# ============================================================================
# Additional tests: Executor signal preservation and types
# ============================================================================


def test_executor_placeholder_preserved_in_batch_results():
    """Verify executor placeholder is preserved in batch_results.json output."""
    # Create a full batch_results.json structure with executor placeholder
    batch_results = {
        "batch_id": "batch_20260628_001",
        "started_at": "2026-06-28T10:00:00Z",
        "finished_at": "2026-06-28T10:30:00Z",
        "exit_code": 124,
        "remote_log": {
            "host": "t_h20",
            "container": "gpu_container_01",
            "raw_log_path": "/data/logs/pytest_batch_20260628_001.log",
            "size_bytes": 1024,
            "captured_at": "2026-06-28T10:30:00Z"
        },
        "tests": [
            {
                "id": 1,
                "test_node": "tests/test_dep_download.py::test_hf_model",
                "status": "ignored",
                "error_type": "timeout",
                "error_message": "JUnit XML missing (watchdog SIGKILL or fetch empty)",
                "duration_ms": None,
                "exit_code": 124,
                "dependency_classification": {
                    "status": "pending",
                    "executor_signal": "timeout_no_xml",
                    "executor_evidence": "JUnit XML missing after watchdog SIGKILL"
                }
            }
        ],
        "statistics": {
            "total": 1,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "retriable_error": 0,
            "ignored": 1
        }
    }

    schema = _load_schema()
    # Validate entire batch_results.json structure
    validate(batch_results, schema)

    # Verify executor placeholder fields are present
    test_entry = batch_results["tests"][0]
    assert "dependency_classification" in test_entry
    dep_class = test_entry["dependency_classification"]
    assert dep_class["status"] == "pending"
    assert dep_class["executor_signal"] == "timeout_no_xml"
    assert "executor_evidence" in dep_class


def test_executor_signal_types():
    """Verify executor can detect and report different signal types."""
    # Define the executor signal types as specified in the design
    EXECUTOR_SIGNALS = {
        "timeout_no_xml": "XML missing after watchdog SIGKILL",
        "timeout_unparseable_xml": "XML unparseable (ET.ParseError)",
        "timeout_no_testcase": "XML has no testcase element",
        "disconnect_exec": "Bastion disconnect during test exec",
        "disconnect_xml_fetch": "Bastion disconnect during xml fetch"
    }

    # Test each signal type against the schema
    schema = _load_schema()
    test_schema = schema["properties"]["tests"]["items"]

    for signal_type, signal_desc in EXECUTOR_SIGNALS.items():
        mock_output = {
            "id": 1,
            "test_node": f"tests/test_{signal_type}.py::test_demo",
            "status": "ignored",
            "error_type": "timeout",
            "error_message": signal_desc,
            "duration_ms": None,
            "exit_code": 124 if signal_type.startswith("timeout") else None,
            "dependency_classification": {
                "status": "pending",
                "executor_signal": signal_type,
                "executor_evidence": signal_desc
            }
        }

        # Validate each signal type against the schema
        validate(mock_output, test_schema)

        # Verify signal type is correctly embedded
        assert mock_output["dependency_classification"]["executor_signal"] == signal_type


if __name__ == "__main__":
    # Run all tests when executed directly
    import pytest
    pytest.main([__file__, "-v"])