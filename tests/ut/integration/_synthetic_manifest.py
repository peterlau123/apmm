"""Synthetic manifest generator for L2 mock pipeline testing.

Generates realistic test manifests with configurable pass/fail/error rates
for testing the pipeline without real SSH calls.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any


def generate_synthetic_manifest(
    n: int,
    pass_rate: float = 0.75,
    fail_rate: float = 0.125,
    error_rate: float = 0.125,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate a synthetic v5 manifest with n test cases.
    
    Args:
        n: Number of test cases to generate
        pass_rate: Target pass rate (default 0.75)
        fail_rate: Target fail rate (default 0.125)
        error_rate: Target error rate (default 0.125)
        seed: Optional random seed for reproducibility
        
    Returns:
        Dict with manifest structure:
        - version: "2.0"
        - tests: list of test dicts (id, test_id, test_node, status, retry_count, max_retry)
        - statistics: totals
        
    Test node IDs are synthetic: "tests/test_file_{i}.py::test_func_{i}"
    """
    if seed is not None:
        random.seed(seed)
    
    rates = {"passed": pass_rate, "failed": fail_rate, "error": error_rate}
    total_rate = sum(rates.values())
    if abs(total_rate - 1.0) > 0.001:
        raise ValueError(f"Rates must sum to 1.0, got {total_rate}")
    
    tests = []
    status_counts = {"passed": 0, "failed": 0, "error": 0, "pending": 0}
    
    for i in range(1, n + 1):
        test_file = f"tests/test_file_{i % 10}.py"
        test_name = f"test_func_{i}"
        test_node = f"{test_file}::{test_name}"
        
        status = random.choices(
            list(rates.keys()),
            weights=list(rates.values()),
            k=1,
        )[0]
        status_counts[status] += 1
        
        test_dict = {
            "id": i,
            "test_id": i,
            "test_node": test_node,
            "test_file": test_file,
            "test_name": test_name,
            "status": status,
            "retry_count": 0,
            "max_retry": 3,
            "last_batch_id": None,
        }
        
        if status == "failed":
            test_dict["error_type"] = "assertion"
            test_dict["error_message"] = f"AssertionError in {test_node}"
        elif status == "error":
            test_dict["error_type"] = random.choice(
                ["dependency", "network", "resource", "collection", "other"]
            )
            test_dict["error_message"] = f"{test_dict['error_type']} error in {test_node}"
        
        tests.append(test_dict)
    
    statistics = {
        "total": n,
        "passed": status_counts["passed"],
        "failed": status_counts["failed"],
        "error": status_counts["error"],
        "pending": status_counts["pending"],
        "executed": n - status_counts["pending"],
        "progress": round((n - status_counts["pending"]) / n * 100, 1) if n > 0 else 0.0,
        "pass_rate": round(status_counts["passed"] / n * 100, 1) if n > 0 else 0.0,
    }
    
    return {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
        "tests": tests,
        "statistics": statistics,
    }


def generate_pending_manifest(n: int, seed: int | None = None) -> dict[str, Any]:
    """Generate a manifest with all tests pending (for batch selector testing).
    
    Args:
        n: Number of test cases
        seed: Optional random seed
        
    Returns:
        Manifest with all tests in pending status
    """
    if seed is not None:
        random.seed(seed)
    
    tests = []
    for i in range(1, n + 1):
        test_file = f"tests/test_file_{i % 10}.py"
        test_name = f"test_func_{i}"
        test_node = f"{test_file}::{test_name}"
        
        tests.append({
            "id": i,
            "test_id": i,
            "test_node": test_node,
            "test_file": test_file,
            "test_name": test_name,
            "status": "pending",
            "retry_count": 0,
            "max_retry": 3,
            "last_batch_id": None,
        })
    
    return {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
        "tests": tests,
        "statistics": {
            "total": n,
            "pending": n,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "executed": 0,
            "progress": 0.0,
            "pass_rate": 0.0,
        },
    }


def simulate_batch_execution(
    batch_config: dict[str, Any],
    pass_rate: float = 0.75,
    fail_rate: float = 0.125,
    error_rate: float = 0.125,
    retriable_rate: float = 0.3,
    seed: int | None = None,
) -> dict[str, Any]:
    """Simulate batch execution with realistic pytest summary structure.
    
    Args:
        batch_config: Batch config dict with tests list
        pass_rate: Pass rate for tests
        fail_rate: Fail rate for tests
        error_rate: Error rate for tests
        retriable_rate: Portion of errors that are retriable (error -> retriable_error)
        seed: Optional random seed
        
    Returns:
        Batch results dict with tests and statistics
    """
    if seed is not None:
        random.seed(seed)
    
    tests = batch_config.get("tests", [])
    results = []
    
    rates = {"passed": pass_rate, "failed": fail_rate, "error": error_rate}
    total_rate = sum(rates.values())
    if abs(total_rate - 1.0) > 0.001:
        raise ValueError(f"Rates must sum to 1.0, got {total_rate}")
    
    status_counts = {"passed": 0, "failed": 0, "error": 0, "retriable_error": 0}
    
    for t in tests:
        status = random.choices(
            list(rates.keys()),
            weights=list(rates.values()),
            k=1,
        )[0]
        
        if status == "error" and random.random() < retriable_rate:
            status = "retriable_error"
        
        status_counts[status] += 1
        
        result = {
            "test_id": t.get("test_id", t.get("id")),
            "test_node": t.get("test_node"),
            "status": status,
            "duration_ms": random.randint(100, 5000),
            "output": f"MOCK {status.upper()}: {t.get('test_node')}",
        }
        
        if status == "failed":
            result["error_type"] = "assertion"
            result["error_message"] = f"AssertionError in {t.get('test_node')}"
        elif status in ("error", "retriable_error"):
            result["error_type"] = random.choice(
                ["dependency", "network", "resource", "collection", "oom", "timeout"]
            )
            result["error_message"] = f"{result['error_type']} error in {t.get('test_node')}"
        
        results.append(result)
    
    batch_id = batch_config.get("batch_id", "mock_batch")
    
    return {
        "batch_id": batch_id,
        "tests": results,
        "statistics": {
            "total": len(results),
            "passed": status_counts["passed"],
            "failed": status_counts["failed"],
            "error": status_counts["error"] + status_counts["retriable_error"],
            "skipped": 0,
        },
        "remote_log": {
            "raw_log_path": f"/mock/path/to/{batch_id}/log.txt",
        },
    }


def simulate_retry_execution(
    previous_results: dict[str, Any],
    retry_success_rate: float = 0.5,
    seed: int | None = None,
) -> dict[str, Any]:
    """Simulate retry execution for retriable errors.
    
    Args:
        previous_results: Previous batch results with retriable_error tests
        retry_success_rate: Rate at which retriable errors become passed on retry
        seed: Optional random seed
        
    Returns:
        Updated batch results with retry outcomes
    """
    if seed is not None:
        random.seed(seed)
    
    results = []
    status_counts = {"passed": 0, "failed": 0, "error": 0, "retriable_error": 0}
    
    for t in previous_results.get("tests", []):
        result = dict(t)
        
        if t.get("status") == "retriable_error":
            if random.random() < retry_success_rate:
                result["status"] = "passed"
                result["output"] = f"MOCK PASS (retry): {t.get('test_node')}"
            else:
                result["status"] = "error"
                result["output"] = f"MOCK ERROR (retry failed): {t.get('test_node')}"
        
        status_counts[result["status"]] += 1
        results.append(result)
    
    return {
        "batch_id": previous_results.get("batch_id", "retry_batch"),
        "tests": results,
        "statistics": {
            "total": len(results),
            "passed": status_counts["passed"],
            "failed": status_counts["failed"],
            "error": status_counts["error"] + status_counts["retriable_error"],
            "skipped": 0,
        },
        "remote_log": previous_results.get("remote_log", {}),
    }