#!/usr/bin/env python3
"""
verify_workflow_test.py - 验证 workflow 执行结果是否符合预期

用法:
    python verify_workflow_test.py --run-dir <run_dir> --test-list <test_list_name>

示例:
    python verify_workflow_test.py --run-dir runs/ut-20260611-120000 --test-list passed
    python verify_workflow_test.py --run-dir runs/ut-20260611-120000 --test-list combined
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional


# 预期状态映射（基于 test_list 名称）
EXPECTED_STATUS_MAP = {
    "passed": {"tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestScaledMMRSModel]": "passed"},
    "failed": {"tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]": "failed"},
    "error": {"tests/compile/distributed/test_async_tp.py::test_async_tp_pass_correctness[False-mp-True-2-meta-llama/Llama-3.2-1B-Instruct]": "error"},
    "combined": {
        "tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestScaledMMRSModel]": "passed",
        "tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]": "failed",
        "tests/compile/distributed/test_async_tp.py::test_async_tp_pass_correctness[False-mp-True-2-meta-llama/Llama-3.2-1B-Instruct]": "error",
    },
}


def load_manifest(run_dir: Path) -> Dict:
    """加载 manifest.json"""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")
    return json.loads(manifest_path.read_text())


def load_batch_results(run_dir: Path, batch_id: str = "batch_001") -> Optional[Dict]:
    """加载 batch_results.json"""
    batch_results_path = run_dir / "batches" / batch_id / "batch_results.json"
    if not batch_results_path.exists():
        return None
    return json.loads(batch_results_path.read_text())


def get_test_status_from_manifest(manifest: Dict, test_name: str) -> Optional[str]:
    """从 manifest 获取测试状态"""
    tests = manifest.get("tests", {})
    test_entry = tests.get(test_name, {})
    return test_entry.get("status")


def verify_single_test(actual_status: str, expected_status: str, test_name: str) -> Dict:
    """验证单个测试结果"""
    passed = actual_status == expected_status
    return {
        "test_name": test_name,
        "expected": expected_status,
        "actual": actual_status,
        "passed": passed,
        "message": f"Expected {expected_status}, got {actual_status}" if not passed else "OK",
    }


def verify_workflow_results(run_dir: Path, test_list_name: str) -> Dict:
    """验证 workflow 执行结果"""
    expected_tests = EXPECTED_STATUS_MAP.get(test_list_name)
    if not expected_tests:
        raise ValueError(f"Unknown test_list: {test_list_name}")

    manifest = load_manifest(run_dir)
    batch_results = load_batch_results(run_dir)

    results = []
    all_passed = True

    for test_name, expected_status in expected_tests.items():
        actual_status = get_test_status_from_manifest(manifest, test_name)
        if actual_status is None:
            actual_status = "not_found"
            all_passed = False
            results.append({
                "test_name": test_name,
                "expected": expected_status,
                "actual": "not_found",
                "passed": False,
                "message": f"Test not found in manifest",
            })
        else:
            verification = verify_single_test(actual_status, expected_status, test_name)
            results.append(verification)
            if not verification["passed"]:
                all_passed = False

    # 统计信息
    manifest_stats = manifest.get("statistics", {})

    return {
        "status": "done" if all_passed else "failed",
        "test_list": test_list_name,
        "run_dir": str(run_dir),
        "verification_results": results,
        "manifest_statistics": manifest_stats,
        "batch_results_available": batch_results is not None,
        "summary": f"{len(results)} tests verified, {sum(1 for r in results if r['passed'])} passed",
    }


def print_report(report: Dict):
    """打印验证报告"""
    print("\n" + "=" * 60)
    print(f"WORKFLOW TEST VERIFICATION REPORT")
    print("=" * 60)
    print(f"Test List: {report['test_list']}")
    print(f"Run Dir: {report['run_dir']}")
    print(f"Status: {report['status']}")
    print(f"Summary: {report['summary']}")
    print("-" * 60)

    print("\nVerification Results:")
    for r in report["verification_results"]:
        status_icon = "✅" if r["passed"] else "❌"
        print(f"  {status_icon} {r['test_name']}")
        print(f"     Expected: {r['expected']}, Actual: {r['actual']}")
        if not r["passed"]:
            print(f"     Message: {r['message']}")

    print("\nManifest Statistics:")
    stats = report["manifest_statistics"]
    print(f"  Passed: {stats.get('passed', 0)}")
    print(f"  Failed: {stats.get('failed', 0)}")
    print(f"  Error: {stats.get('error', 0)}")
    print(f"  Pending: {stats.get('pending', 0)}")
    print(f"  Ignored: {stats.get('ignored', 0)}")

    print("\nBatch Results Available:", report["batch_results_available"])
    print("=" * 60)

    if report["status"] == "done":
        print("\n✅ VERIFICATION PASSED")
    else:
        print("\n⚠️ VERIFICATION FAILED - check above for details")
    print()


def main():
    parser = argparse.ArgumentParser(description="Verify workflow test results")
    parser.add_argument("--run-dir", required=True, help="Workflow run directory")
    parser.add_argument("--test-list", required=True,
                        choices=["passed", "failed", "error", "combined"],
                        help="Test list name")

    args = parser.parse_args()
    run_dir = Path(args.run_dir)

    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}")
        return 1

    report = verify_workflow_results(run_dir, args.test_list)
    print_report(report)

    return 0 if report["status"] == "done" else 1


if __name__ == "__main__":
    exit(main())