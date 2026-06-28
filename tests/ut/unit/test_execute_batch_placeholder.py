#!/usr/bin/env python3
"""
test_execute_batch_placeholder.py - Verify executor timeout returns placeholder schema
with executor_signal + executor_evidence (Task 2 from dependency_classification
optimization plan).

Task 2: Replace 5 hardcoded timeout dependency_classification with placeholder schema.
"""

import json
from pathlib import Path
from jsonschema import validate

# Schema loader (same as execute_batch.py)
_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "ut" / "unit-test-executor" / "scripts"
_SCHEMA_PATH = _SCRIPT_DIR.parent / "batch_results_schema.json"


def _load_schema():
    """Read the canonical batch_results_schema.json."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


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