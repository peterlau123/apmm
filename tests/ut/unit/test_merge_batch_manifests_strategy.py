"""Tests for merge_batch_manifests strategy logic"""
import pytest
from tasks.ut.scripts.merge_batch_manifests import merge_batch_results


def test_all_strategy_updates_all():
    """Test that 'all' strategy updates all statuses including failed."""
    manifest = {"tests": [{"id": 1, "status": "pending"}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "failed"}]}

    result = merge_batch_results(manifest, batch, strategy="all")
    assert result["tests"][0]["status"] == "failed"


def test_passed_only_skips_failed():
    """Test that 'passed-only' strategy skips failed tests."""
    manifest = {"tests": [{"id": 1, "status": "pending"}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "failed"}]}

    result = merge_batch_results(manifest, batch, strategy="passed-only")
    assert result["tests"][0]["status"] == "pending"  # Unchanged


def test_passed_only_updates_passed():
    """Test that 'passed-only' strategy updates passed tests."""
    manifest = {"tests": [{"id": 1, "status": "pending", "run_count": 0}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "passed"}]}

    result = merge_batch_results(manifest, batch, strategy="passed-only")
    assert result["tests"][0]["status"] == "passed"


def test_counter_logic_first_failure():
    """Test counter logic for first failure (not retry)."""
    manifest = {"tests": [{"id": 1, "status": "pending", "run_count": 0, "retry_count": 0}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "failed"}]}

    result = merge_batch_results(manifest, batch, strategy="all")
    assert result["tests"][0]["run_count"] == 1
    assert result["tests"][0]["retry_count"] == 0  # First failure, not retry


def test_counter_logic_retry():
    """Test counter logic for retry (previous status was failed)."""
    manifest = {"tests": [{"id": 1, "status": "failed", "run_count": 1, "retry_count": 0}]}
    batch = {"batch_id": "b2", "tests": [{"id": 1, "status": "failed"}]}

    result = merge_batch_results(manifest, batch, strategy="all")
    assert result["tests"][0]["run_count"] == 2
    assert result["tests"][0]["retry_count"] == 1  # This is a retry


def test_passed_only_counter_updated_for_passed():
    """Test that counters are updated for passed tests in passed-only strategy."""
    manifest = {"tests": [{"id": 1, "status": "pending", "run_count": 0, "retry_count": 0}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "passed"}]}

    result = merge_batch_results(manifest, batch, strategy="passed-only")
    assert result["tests"][0]["run_count"] == 1
    assert result["tests"][0]["last_batch_id"] == "b1"


def test_strategy_default_is_all():
    """Test that default strategy is 'all'."""
    manifest = {"tests": [{"id": 1, "status": "pending"}]}
    batch = {"batch_id": "b1", "tests": [{"id": 1, "status": "failed"}]}

    result = merge_batch_results(manifest, batch)  # No strategy param
    assert result["tests"][0]["status"] == "failed"