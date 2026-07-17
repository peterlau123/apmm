"""Tests for v5 schema additions: retriable_error status, oom/timeout error_type,
last_batch_id pointer, and per-test max_retry."""
import pytest
from skills.ut.ut_common.validate_schema import validate_manifest


def _base_manifest(test_overrides):
    """Build a minimally valid manifest with one test, overriding test fields."""
    test = {
        "id": 1,
        "test_node": "tests/test_x.py::TestX::test_t1",
        "test_file": "tests/test_x.py",
        "test_name": "test_t1",
        "status": "pending",
    }
    test.update(test_overrides)
    return {
        "version": "2.0",
        "generated_at": "2026-06-19T00:00:00Z",
        "source": "pytest_collect",
        "tests": [test],
        "statistics": {"total": 1, "pending": 1},
    }


# --- Task 1.1 ---

def test_status_retriable_error_is_valid():
    manifest = _base_manifest({"status": "retriable_error", "retry_count": 0, "max_retry": 3})
    validate_manifest(manifest)


def test_error_type_oom_is_valid():
    manifest = _base_manifest({
        "status": "retriable_error", "error_type": "oom",
        "retry_count": 0, "max_retry": 3,
    })
    validate_manifest(manifest)


def test_error_type_timeout_is_valid():
    manifest = _base_manifest({
        "status": "retriable_error", "error_type": "timeout",
        "retry_count": 0, "max_retry": 3,
    })
    validate_manifest(manifest)


# --- Task 1.2 ---

def test_last_batch_id_string_is_valid():
    manifest = _base_manifest({
        "status": "failed", "last_batch_id": "batch_20260619_001",
        "retry_count": 1, "max_retry": 3,
    })
    validate_manifest(manifest)


def test_max_retry_negative_is_invalid():
    manifest = _base_manifest({"status": "pending", "retry_count": 0, "max_retry": -1})
    with pytest.raises(Exception):
        validate_manifest(manifest)
