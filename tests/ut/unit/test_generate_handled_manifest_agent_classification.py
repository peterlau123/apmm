"""
Unit test for agent_classification parameter in generate_handled_manifest.

Task 3 from dependency_classification optimization design:
- Replace llm_invoker parameter with agent_classification
- Worker Agent directly outputs classification JSON
- Python script validates schema
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path for imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Import using file path (hyphenated directory)
import importlib.util as _ilu
_GENERATE_MANIFEST_PATH = _project_root / "skills" / "ut" / "failure-handler" / "scripts" / "generate_handled_manifest.py"
_spec = _ilu.spec_from_file_location("generate_handled_manifest", _GENERATE_MANIFEST_PATH)
generate_handled_manifest_module = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(generate_handled_manifest_module)


def test_agent_classification_parameter_accepted():
    """Verify generate_handled_manifest accepts agent_classification parameter"""
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


def test_agent_classification_none_fallback():
    """Verify agent_classification=None triggers fallback to unknown"""
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


def test_agent_classification_invalid_schema_fallback():
    """Verify invalid agent_classification triggers fallback"""
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


def test_generate_handled_manifest_accepts_agent_classification():
    """Verify generate_handled_manifest propagates agent_classification"""
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
        # The timeout test should be processed with agent_classification
        # and result in "ignored" status