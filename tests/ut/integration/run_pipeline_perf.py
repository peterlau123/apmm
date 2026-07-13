#!/usr/bin/env python3
"""Pipeline performance harness with mock/real execution modes.

Wires the full v5 foundation pipeline with configurable execution mode.
Supports mock mode (synthetic results) for local testing without SSH.

Usage:
    # Mock mode (no SSH) - default 3 tests
    python tests/ut/integration/run_pipeline_perf.py --n 3 --mode mock

    # Mock mode with custom pass/fail/error rates
    python tests/ut/integration/run_pipeline_perf.py --n 32 --mode mock --pass-rate 0.75 --fail-rate 0.125 --error-rate 0.125

    # Real mode (remote SSH)
    python tests/ut/integration/run_pipeline_perf.py --n 3 --mode real

    # Seed from existing manifest
    python tests/ut/integration/run_pipeline_perf.py --n 10 --mode mock --seed-from runs/batch_001/manifest.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import shutil
import sys
import time
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.ut.integration._perf import PerfMetrics
from tests.ut.integration._synthetic_manifest import (
    generate_pending_manifest,
    simulate_batch_execution,
    simulate_retry_execution,
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_BS = _load_module(
    "perf_generate_batch",
    _PROJECT_ROOT / "skills" / "ut" / "batch-selector" / "scripts" / "generate_batch.py",
)
_EXEC = _load_module(
    "perf_execute_batch",
    _PROJECT_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts" / "execute_batch.py",
)
_MU = _load_module(
    "perf_update_manifest",
    _PROJECT_ROOT / "skills" / "ut" / "manifest-updater" / "scripts" / "update_manifest.py",
)
_FH = _load_module(
    "perf_analyze_failures",
    _PROJECT_ROOT / "skills" / "ut" / "failure-handler" / "scripts" / "analyze_failures.py",
)
_HR = _load_module(
    "perf_ut_runner",
    _PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "ut_runner.py",
)

from skills.ut.shared.validate_schema import validate_manifest  # noqa: E402


RUN_ID = "perf-test"
REMOTE_SERVER = "t_h20"
DOCKER_CONTAINER = "v0.13.0_torch2.5.1_compile"
TIMEOUT = 600


def build_manifest(test_nodes: list[str]) -> dict:
    """Build a minimal valid manifest from a list of pytest test_nodes."""
    tests = []
    for i, node in enumerate(test_nodes, start=1):
        test_file, _, test_name = node.partition("::")
        tests.append({
            "id": i,
            "test_id": i,
            "test_node": node,
            "test_file": test_file,
            "test_name": test_name,
            "status": "pending",
            "retry_count": 0,
            "max_retry": 3,
            "last_batch_id": None,
        })
    return {
        "version": "2.0",
        "generated_at": "2026-06-20T00:00:00Z",
        "source": "manual",
        "tests": tests,
        "statistics": {
            "total": len(tests),
            "passed": 0,
            "failed": 0,
            "error": 0,
            "pending": len(tests),
            "executed": 0,
            "progress": 0.0,
        },
    }


def write_workflow_state(run_dir: Path, manifest_path: Path) -> None:
    """Write a minimal workflow_state.json."""
    state = {
        "run_id": RUN_ID,
        "iteration": 0,
        "current_stage": "execute",
        "paths": {
            "manifest": str(manifest_path),
            "run_dir": str(run_dir),
            "batches_dir": str(run_dir),
        },
        "config": {
            "remote": {
                "server": REMOTE_SERVER,
                "docker": DOCKER_CONTAINER,
                "vllm_dir": "/gpfs/gcsp/M2.7_verify/vllm",
            },
            "timeout": TIMEOUT,
        },
        "stats": {},
        "flags": {},
    }
    (run_dir / "workflow_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def mock_run_remote(
    batch_config_path: Path,
    exec_config: dict,
    pass_rate: float = 0.75,
    fail_rate: float = 0.125,
    error_rate: float = 0.125,
    retriable_rate: float = 0.3,
    seed: int | None = None,
) -> dict:
    """Mock run_remote that returns synthetic pytest results.
    
    Args:
        batch_config_path: Path to batch_config.json
        exec_config: Execution config dict
        pass_rate: Pass rate for tests
        fail_rate: Fail rate for tests
        error_rate: Error rate for tests
        retriable_rate: Portion of errors that are retriable
        seed: Optional random seed
        
    Returns:
        Batch results dict with realistic pytest summary structure:
        - tests: list with test_node, status, duration_ms, output
        - statistics: passed, failed, error, skipped counts
    """
    batch_config = json.loads(batch_config_path.read_text(encoding="utf-8"))
    
    return simulate_batch_execution(
        batch_config,
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        error_rate=error_rate,
        retriable_rate=retriable_rate,
        seed=seed,
    )


def run_pipeline(
    n: int,
    mode: str,
    seed_from: Path | None = None,
    fixture_path: Path | None = None,
    pass_rate: float = 0.75,
    fail_rate: float = 0.125,
    error_rate: float = 0.125,
    retriable_rate: float = 0.3,
    seed: int | None = None,
) -> dict:
    """Run the full pipeline and return metrics.
    
    Args:
        n: Number of tests to run
        mode: "mock" or "real"
        seed_from: Optional path to existing manifest to seed from
        fixture_path: Optional path to test fixture file
        pass_rate: Pass rate for mock mode (default 0.75)
        fail_rate: Fail rate for mock mode (default 0.125)
        error_rate: Error rate for mock mode (default 0.125)
        retriable_rate: Retriable error rate for mock mode (default 0.3)
        seed: Optional random seed for reproducibility
        
    Returns:
        Dict with metrics and results
    """
    metrics = PerfMetrics(mode=mode, n=n)
    
    run_dir = _PROJECT_ROOT / "runs" / f"perf-{RUN_ID}"
    batch_id = f"batch_perf_{mode}"
    batch_dir = run_dir / batch_id
    batch_config_path = batch_dir / "batch_config.json"
    manifest_path = run_dir / "manifest.json"
    
    if run_dir.exists():
        shutil.rmtree(run_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)
    
    t0 = time.time()
    
    # Step 1: Load or build manifest (use synthetic manifest in mock mode)
    t1 = time.time()
    if seed_from and seed_from.exists():
        manifest = json.loads(seed_from.read_text(encoding="utf-8"))
        test_nodes = [t["test_node"] for t in manifest.get("tests", [])[:n]]
        manifest = build_manifest(test_nodes)
    elif fixture_path and fixture_path.exists():
        test_nodes = [
            ln.strip()
            for ln in fixture_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ][:n]
        manifest = build_manifest(test_nodes)
    elif mode == "mock":
        manifest = generate_pending_manifest(n=n, seed=seed)
    else:
        manifest = build_manifest([])
    
    try:
        validate_manifest(manifest)
    except Exception as e:
        return {"error": f"manifest validation failed: {e}"}
    
    metrics.record_stage("manifest_build", int((time.time() - t1) * 1000))
    write_workflow_state(run_dir, manifest_path)
    
    # Step 2: select_batch + write_batch_config
    t2 = time.time()
    selected = _BS.select_batch(manifest, batch_size=n)
    cfg = _BS.write_batch_config(
        path=batch_config_path,
        batch_id=batch_id,
        iteration=0,
        run_id=RUN_ID,
        selected=selected,
    )
    metrics.record_stage("batch_select", int((time.time() - t2) * 1000))
    
    # Step 3: execute_batch
    t3 = time.time()
    exec_cfg = _HR.get_execute_config(run_dir / "workflow_state.json")
    
    if mode == "mock":
        batch_results = mock_run_remote(
            batch_config_path,
            exec_cfg,
            pass_rate=pass_rate,
            fail_rate=fail_rate,
            error_rate=error_rate,
            retriable_rate=retriable_rate,
            seed=seed,
        )
    else:
        batch_results = _EXEC.execute_batch(
            batch_config_path, run_dir / "workflow_state.json", exec_config=exec_cfg
        )
    
    metrics.record_stage("execute", int((time.time() - t3) * 1000))
    
    if batch_results.get("next_action") == "wait":
        return {"error": "Bastion disconnect during execution"}
    
    # Bug #3 fix: execute_batch returns summary dict (batch_id, batch_results_path, stats)
    # We need to read the FULL batch_results from the path for subsequent processing
    batch_results_path = Path(batch_results.get("batch_results_path", batch_dir / "batch_results.json"))
    if batch_results_path.exists():
        full_batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))
    else:
        # Fallback for mock mode where batch_results is already the full dict
        full_batch_results = batch_results
    
    # Step 4: Analyze failures
    t4 = time.time()
    failed_tests = [
        t for t in full_batch_results.get("tests", [])
        if t.get("status") in ("failed", "error", "retriable_error")
    ]
    _FH.filter_processable(full_batch_results.get("tests", []))
    metrics.record_stage("analyze", int((time.time() - t4) * 1000))
    
    # Step 5: Update manifest
    t5 = time.time()
    handled = {"tests": []}
    updated_manifest = _MU.update_manifest(manifest, full_batch_results, handled)
    manifest_path.write_text(
        json.dumps(updated_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics.record_stage("update_manifest", int((time.time() - t5) * 1000))
    
    wall_clock_s = time.time() - t0
    
    stats = full_batch_results.get("statistics", {})
    final_metrics = metrics.finalize(
        total=stats.get("total", 0),
        passed=stats.get("passed", 0),
        failed=stats.get("failed", 0),
        error=stats.get("error", 0),
        wall_clock_s=wall_clock_s,
    )
    
    return {
        "metrics": final_metrics,
        "batch_results": full_batch_results,
        "manifest_path": str(manifest_path),
        "batch_config_path": str(batch_config_path),
        "manifest": updated_manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline performance harness")
    parser.add_argument("--n", type=int, default=3, help="Number of tests to run")
    parser.add_argument(
        "--mode", choices=["mock", "real"], default="mock", help="Execution mode"
    )
    parser.add_argument(
        "--seed-from", type=Path, help="Path to existing manifest to seed from"
    )
    parser.add_argument(
        "--fixture", type=Path,
        help="Path to test fixture file (one test_node per line)"
    )
    parser.add_argument(
        "--pass-rate", type=float, default=0.75,
        help="Pass rate for mock mode (default 0.75)"
    )
    parser.add_argument(
        "--fail-rate", type=float, default=0.125,
        help="Fail rate for mock mode (default 0.125)"
    )
    parser.add_argument(
        "--error-rate", type=float, default=0.125,
        help="Error rate for mock mode (default 0.125)"
    )
    parser.add_argument(
        "--retriable-rate", type=float, default=0.3,
        help="Portion of errors that are retriable (default 0.3)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default 42)"
    )
    parser.add_argument(
        "--output", type=Path,
        help="Path to write JSON output (for batch collection)"
    )
    args = parser.parse_args()
    
    # Validate rate sum
    rate_sum = args.pass_rate + args.fail_rate + args.error_rate
    if abs(rate_sum - 1.0) > 0.001:
        print(f"[ERROR] Rates must sum to 1.0, got {rate_sum}")
        return 1
    
    print("=" * 70)
    print(f"v5 PIPELINE PERF HARNESS — mode={args.mode}, n={args.n}")
    if args.mode == "mock":
        print(f"  pass_rate={args.pass_rate}, fail_rate={args.fail_rate}, error_rate={args.error_rate}")
    print("=" * 70)
    
    if args.mode == "real":
        print("WARNING: Real mode will make SSH calls to remote server!")
    
    result = run_pipeline(
        n=args.n,
        mode=args.mode,
        seed_from=args.seed_from,
        fixture_path=args.fixture,
        pass_rate=args.pass_rate,
        fail_rate=args.fail_rate,
        error_rate=args.error_rate,
        retriable_rate=args.retriable_rate,
        seed=args.seed,
    )
    
    if "error" in result:
        print(f"[FAIL] {result['error']}")
        return 1
    
    metrics = result["metrics"]
    print("\n" + "=" * 70)
    print("PERFORMANCE METRICS")
    print("=" * 70)
    print(f"  Mode:            {metrics['mode']}")
    print(f"  Tests:           {metrics['total']}")
    print(f"  Passed:          {metrics['passed']}")
    print(f"  Failed:          {metrics['failed']}")
    print(f"  Error:           {metrics['error']}")
    print(f"  Wall Clock:      {metrics['wall_clock_s']:.3f}s")
    print(f"  Throughput:      {metrics['throughput_per_min']:.2f} tests/min")
    print("\nStage Timings (ms):")
    for stage, ms in metrics["stage_ms"].items():
        print(f"  {stage:20s}: {ms:6d} ms")
    
    # Write output JSON if requested
    if args.output:
        output_data = {
            "metrics": metrics,
            "batch_results": result.get("batch_results"),
            "manifest_final": result.get("manifest"),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
        print(f"\nOutput written to: {args.output}")
    
    print("\n" + "=" * 70)
    if metrics["passed"] == metrics["total"] and metrics["total"] > 0:
        print(f"PIPELINE: PASS — {metrics['passed']}/{metrics['total']} tests passed")
        return 0
    else:
        print(f"PIPELINE: PARTIAL — {metrics['passed']}/{metrics['total']} passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())