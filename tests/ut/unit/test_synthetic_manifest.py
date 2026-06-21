"""Unit tests for synthetic manifest generator.

Tests schema validation, rate distribution, and n=8/16/32 generation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from tests.ut.integration._synthetic_manifest import (
    generate_synthetic_manifest,
    generate_pending_manifest,
    simulate_batch_execution,
    simulate_retry_execution,
)
from skills.ut.shared.validate_schema import validate_manifest


class TestSyntheticManifestSchema:
    """Test schema validation for generated manifests."""
    
    def test_generate_validates_against_schema(self):
        """Generated manifest should validate against manifest_schema.json."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        validate_manifest(manifest)
    
    def test_generate_pending_validates(self):
        """Pending manifest should validate."""
        manifest = generate_pending_manifest(n=8, seed=42)
        validate_manifest(manifest)
    
    def test_n_16_validates(self):
        """n=16 manifest validates."""
        manifest = generate_synthetic_manifest(n=16, seed=42)
        validate_manifest(manifest)
    
    def test_n_32_validates(self):
        """n=32 manifest validates."""
        manifest = generate_synthetic_manifest(n=32, seed=42)
        validate_manifest(manifest)
    
    def test_all_required_fields_present(self):
        """All required fields from schema should be present."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        
        assert "version" in manifest
        assert manifest["version"] == "2.0"
        
        assert "generated_at" in manifest
        assert "source" in manifest
        assert manifest["source"] == "manual"
        
        assert "tests" in manifest
        assert len(manifest["tests"]) == 8
        
        assert "statistics" in manifest
        
        stats = manifest["statistics"]
        assert stats["total"] == 8
        assert stats["passed"] + stats["failed"] + stats["error"] + stats["pending"] == 8


class TestSyntheticManifestRateDistribution:
    """Test that generated status distributions match configured rates."""
    
    def test_default_rates_approximate(self):
        """With default rates (0.75/0.125/0.125), large sample should match."""
        manifest = generate_synthetic_manifest(n=1000, seed=42)
        stats = manifest["statistics"]
        
        passed_pct = stats["passed"] / stats["total"]
        failed_pct = stats["failed"] / stats["total"]
        error_pct = stats["error"] / stats["total"]
        
        assert 0.70 <= passed_pct <= 0.80
        assert 0.10 <= failed_pct <= 0.15
        assert 0.10 <= error_pct <= 0.15
    
    def test_custom_rates_high_fail(self):
        """High fail rate should produce more failed tests."""
        manifest = generate_synthetic_manifest(
            n=1000,
            pass_rate=0.25,
            fail_rate=0.70,
            error_rate=0.05,
            seed=42,
        )
        stats = manifest["statistics"]
        
        failed_pct = stats["failed"] / stats["total"]
        
        assert 0.65 <= failed_pct <= 0.75
    
    def test_all_pass(self):
        """All pass rate should produce all passed."""
        manifest = generate_synthetic_manifest(
            n=32,
            pass_rate=1.0,
            fail_rate=0.0,
            error_rate=0.0,
            seed=42,
        )
        stats = manifest["statistics"]
        
        assert stats["passed"] == 32
        assert stats["failed"] == 0
        assert stats["error"] == 0
    
    def test_all_fail(self):
        """All fail rate should produce all failed."""
        manifest = generate_synthetic_manifest(
            n=32,
            pass_rate=0.0,
            fail_rate=1.0,
            error_rate=0.0,
            seed=42,
        )
        stats = manifest["statistics"]
        
        assert stats["passed"] == 0
        assert stats["failed"] == 32
        assert stats["error"] == 0
    
    def test_rates_sum_validation(self):
        """Rates not summing to 1.0 should raise ValueError."""
        with pytest.raises(ValueError, match="Rates must sum to 1.0"):
            generate_synthetic_manifest(
                n=8,
                pass_rate=0.5,
                fail_rate=0.3,
                error_rate=0.3,
            )


class TestSyntheticManifestTestStructure:
    """Test structure of individual test entries."""
    
    def test_test_node_format(self):
        """Test node IDs follow expected format."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        
        for test in manifest["tests"]:
            assert "::" in test["test_node"]
            assert test["test_node"].startswith("tests/")
            assert ".py::" in test["test_node"]
    
    def test_required_test_fields(self):
        """Each test should have required fields."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        
        required_fields = ["id", "test_id", "test_node", "test_file", "test_name", "status"]
        
        for test in manifest["tests"]:
            for field in required_fields:
                assert field in test
    
    def test_id_sequence(self):
        """IDs should be sequential starting from 1."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        
        ids = [t["id"] for t in manifest["tests"]]
        assert ids == list(range(1, 9))
    
    def test_failed_has_error_fields(self):
        """Failed tests should have error_type and error_message."""
        manifest = generate_synthetic_manifest(
            n=32,
            pass_rate=0.0,
            fail_rate=1.0,
            error_rate=0.0,
            seed=42,
        )
        
        for test in manifest["tests"]:
            assert test["status"] == "failed"
            assert test["error_type"] == "assertion"
            assert test["error_message"] is not None
    
    def test_error_has_error_fields(self):
        """Error tests should have error_type and error_message."""
        manifest = generate_synthetic_manifest(
            n=32,
            pass_rate=0.0,
            fail_rate=0.0,
            error_rate=1.0,
            seed=42,
        )
        
        for test in manifest["tests"]:
            assert test["status"] == "error"
            assert test["error_type"] is not None
            assert test["error_message"] is not None


class TestPendingManifest:
    """Test pending manifest generation."""
    
    def test_all_pending(self):
        """All tests should be pending."""
        manifest = generate_pending_manifest(n=32, seed=42)
        
        for test in manifest["tests"]:
            assert test["status"] == "pending"
        
        stats = manifest["statistics"]
        assert stats["pending"] == 32
        assert stats["passed"] == 0
        assert stats["failed"] == 0
        assert stats["error"] == 0
    
    def test_pending_validates(self):
        """Pending manifest should validate against schema."""
        manifest = generate_pending_manifest(n=32, seed=42)
        validate_manifest(manifest)


class TestSimulateBatchExecution:
    """Test batch execution simulation."""
    
    def test_batch_results_structure(self):
        """Batch results should have correct structure."""
        batch_config = {
            "batch_id": "test_batch",
            "tests": [
                {"test_id": 1, "test_node": "tests/test_file_1.py::test_func_1"},
                {"test_id": 2, "test_node": "tests/test_file_1.py::test_func_2"},
            ],
        }
        
        results = simulate_batch_execution(batch_config, seed=42)
        
        assert "batch_id" in results
        assert "tests" in results
        assert "statistics" in results
        assert "remote_log" in results
    
    def test_statistics_sum(self):
        """Statistics should sum correctly."""
        batch_config = {
            "batch_id": "test_batch",
            "tests": [
                {"test_id": i, "test_node": f"tests/test.py::test_{i}"}
                for i in range(1, 33)
            ],
        }
        
        results = simulate_batch_execution(batch_config, seed=42)
        stats = results["statistics"]
        
        assert stats["passed"] + stats["failed"] + stats["error"] == stats["total"]
    
    def test_retriable_errors(self):
        """Some errors should be retriable with retriable_rate."""
        batch_config = {
            "batch_id": "test_batch",
            "tests": [
                {"test_id": i, "test_node": f"tests/test.py::test_{i}"}
                for i in range(1, 101)
            ],
        }
        
        results = simulate_batch_execution(
            batch_config,
            pass_rate=0.0,
            fail_rate=0.0,
            error_rate=1.0,
            retriable_rate=0.3,
            seed=42,
        )
        
        retriable_count = sum(
            1 for t in results["tests"] if t["status"] == "retriable_error"
        )
        error_count = sum(1 for t in results["tests"] if t["status"] == "error")
        
        assert retriable_count > 0
        assert error_count > 0


class TestSimulateRetryExecution:
    """Test retry execution simulation."""
    
    def test_retry_changes_status(self):
        """Retriable errors should change on retry."""
        previous_results = {
            "batch_id": "batch_1",
            "tests": [
                {"test_id": 1, "test_node": "tests/test.py::test_1", "status": "retriable_error"},
                {"test_id": 2, "test_node": "tests/test.py::test_2", "status": "passed"},
            ],
            "remote_log": {"raw_log_path": "/mock/path"},
        }
        
        results = simulate_retry_execution(previous_results, seed=42)
        
        retriable_test = results["tests"][0]
        assert retriable_test["status"] in ("passed", "error")
    
    def test_passed_stays_passed(self):
        """Passed tests should stay passed on retry."""
        previous_results = {
            "batch_id": "batch_1",
            "tests": [
                {"test_id": 1, "test_node": "tests/test.py::test_1", "status": "passed"},
            ],
            "remote_log": {},
        }
        
        results = simulate_retry_execution(previous_results, seed=42)
        
        assert results["tests"][0]["status"] == "passed"
    
    def test_retry_success_rate(self):
        """Retry success rate should affect outcomes."""
        previous_results = {
            "batch_id": "batch_1",
            "tests": [
                {"test_id": i, "test_node": f"tests/test.py::test_{i}", "status": "retriable_error"}
                for i in range(1, 101)
            ],
            "remote_log": {},
        }
        
        results_high = simulate_retry_execution(previous_results, retry_success_rate=0.8, seed=42)
        passed_high = sum(1 for t in results_high["tests"] if t["status"] == "passed")
        
        results_low = simulate_retry_execution(previous_results, retry_success_rate=0.2, seed=42)
        passed_low = sum(1 for t in results_low["tests"] if t["status"] == "passed")
        
        assert passed_high > passed_low


class TestN8N16N32Generation:
    """Test generation for specific n values as required by Phase 3."""
    
    def test_n_8(self):
        """n=8 generation works."""
        manifest = generate_synthetic_manifest(n=8, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 8
    
    def test_n_16(self):
        """n=16 generation works."""
        manifest = generate_synthetic_manifest(n=16, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 16
    
    def test_n_32(self):
        """n=32 generation works."""
        manifest = generate_synthetic_manifest(n=32, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 32
    
    def test_n_8_pending(self):
        """n=8 pending generation works."""
        manifest = generate_pending_manifest(n=8, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 8
        assert all(t["status"] == "pending" for t in manifest["tests"])
    
    def test_n_16_pending(self):
        """n=16 pending generation works."""
        manifest = generate_pending_manifest(n=16, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 16
        assert all(t["status"] == "pending" for t in manifest["tests"])
    
    def test_n_32_pending(self):
        """n=32 pending generation works."""
        manifest = generate_pending_manifest(n=32, seed=42)
        validate_manifest(manifest)
        assert len(manifest["tests"]) == 32
        assert all(t["status"] == "pending" for t in manifest["tests"])