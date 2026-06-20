#!/usr/bin/env python3
"""Linear-mode v5 pipeline integration smoke harness.

Wires the full v5 foundation pipeline end-to-end on REAL remote execution
with a tiny batch (3 lightweight tests). NOT a pytest test — this is a
runnable script that performs real remote pytest via tools/agent.py.

Pipeline:
  1. Build tiny manifest (3 tests) -> validate_manifest
  2. select_batch -> write_batch_config (raw selector output, no reshaping)
  3. get_execute_config(state) -> execute_batch(..., exec_config=) (REAL remote
     pytest) -> writes summary.txt + batch_results.json
  4. analyze_failed_tests_v5(filter_processable on failures)
  5. update_manifest(handled={"tests":[]}) -> manifest.json
  6. Print PASS/FAIL summary

Usage:
    cd D:/workspace/apmm
    python tests/integration/run_linear_smoke.py
"""

import importlib.util
import json
import shutil
import sys
import traceback
from pathlib import Path

# Project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load v5 modules from skill scripts
_BS = _load_module(
    "smoke_generate_batch",
    _PROJECT_ROOT / "skills" / "ut" / "batch-selector" / "scripts" / "generate_batch.py",
)
_EXEC = _load_module(
    "smoke_execute_batch",
    _PROJECT_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts" / "execute_batch.py",
)
_MU = _load_module(
    "smoke_update_manifest",
    _PROJECT_ROOT / "skills" / "ut" / "manifest-updater" / "scripts" / "update_manifest.py",
)
_FH = _load_module(
    "smoke_analyze_failures",
    _PROJECT_ROOT / "skills" / "ut" / "failure-handler" / "scripts" / "analyze_failures.py",
)
_HR = _load_module(
    "smoke_hermes_runner",
    _PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "hermes_runner.py",
)

from skills.ut.shared.validate_schema import validate_manifest  # noqa: E402


# ── Constants ─────────────────────────────────────────────────────────────────
RUN_ID = "smoke-test"
RUN_DIR = _PROJECT_ROOT / "runs" / f"smoke-{RUN_ID}"
BATCH_ID = "batch_smoke"
BATCH_DIR = RUN_DIR / BATCH_ID
WORKFLOW_STATE_PATH = RUN_DIR / "workflow_state.json"
BATCH_CONFIG_PATH = BATCH_DIR / "batch_config.json"
MANIFEST_PATH = RUN_DIR / "manifest.json"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mini_test_list.txt"

REMOTE_SERVER = "t_h20"
DOCKER_CONTAINER = "v0.13.0_torch2.5.1_compile"
TIMEOUT = 600


def build_manifest(test_nodes: list[str]) -> dict:
    """Build a minimal valid manifest from a list of pytest test_nodes."""
    tests = []
    for i, node in enumerate(test_nodes, start=1):
        # node is "tests/file.py::test_name[param]" — split on first ::
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


def write_workflow_state() -> None:
    """Write a minimal workflow_state.json that get_execute_config can read.

    Config is nested under state["config"]["remote"] so that
    hermes_runner.get_execute_config(state_path) flattens it into the flat keys
    execute_batch expects (remote_server, docker_container, timeout, ...).
    """
    state = {
        "run_id": RUN_ID,
        "iteration": 0,
        "current_stage": "execute",
        "paths": {
            "manifest": str(MANIFEST_PATH),
            "run_dir": str(RUN_DIR),
            "batches_dir": str(RUN_DIR),
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
    WORKFLOW_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    print("=" * 70)
    print("v5 LINEAR PIPELINE SMOKE — apmm/tests/integration/run_linear_smoke.py")
    print("=" * 70)

    # Clean / recreate run dir
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Load fixture and build manifest
    test_nodes = [
        ln.strip()
        for ln in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    print(f"[1] Fixture: {len(test_nodes)} tests")
    for n in test_nodes:
        print(f"    - {n}")

    manifest = build_manifest(test_nodes)
    try:
        validate_manifest(manifest)
        print("[1] manifest validates OK")
    except Exception as e:
        print(f"[FAIL] manifest validation: {e}")
        return 2

    write_workflow_state()
    print(f"[1] workflow_state.json written: {WORKFLOW_STATE_PATH}")

    # Step 2: select_batch + write_batch_config
    selected = _BS.select_batch(manifest, batch_size=8)
    print(f"[2] select_batch -> {len(selected)} tests selected")

    cfg = _BS.write_batch_config(
        path=BATCH_CONFIG_PATH,
        batch_id=BATCH_ID,
        iteration=0,
        run_id=RUN_ID,
        selected=selected,
    )
    # Raw selector output flows straight into execute_batch — no reshaping.
    # execute_batch tolerates `test_id` (G4 fix), so selected dicts pass through
    # unchanged.
    print(f"[2] batch_config.json written: {BATCH_CONFIG_PATH}")
    print(f"    keys: {sorted(cfg.keys())}")

    # Step 3: execute_batch — REAL remote pytest
    print("[3] execute_batch — running remote pytest (this may take minutes)...")
    exec_cfg = _HR.get_execute_config(WORKFLOW_STATE_PATH)
    try:
        exec_result = _EXEC.execute_batch(
            BATCH_CONFIG_PATH, WORKFLOW_STATE_PATH, exec_config=exec_cfg
        )
    except Exception as e:
        print(f"[FAIL] execute_batch raised: {e}")
        traceback.print_exc()
        return 3

    print(f"[3] execute_batch returned: {json.dumps(exec_result, indent=2)}")

    if exec_result.get("next_action") == "wait":
        print("[STOP] Bastion disconnect during execution. Reporting and stopping.")
        return 4

    # Step 4: load batch_results.json + analyze
    batch_results_path = BATCH_DIR / "batch_results.json"
    summary_path = BATCH_DIR / "summary.txt"

    if not batch_results_path.exists():
        print(f"[FAIL] batch_results.json missing: {batch_results_path}")
        return 5

    batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))

    failed_tests = [t for t in batch_results.get("tests", [])
                    if t.get("status") in ("failed", "error")]
    print(f"[4] {len(failed_tests)} failed/error tests; running filter_processable...")

    processable = _FH.filter_processable(batch_results.get("tests", []))
    print(f"[4] filter_processable -> {len(processable)} processable tests")

    # Skip ensure_on_branch network call — it would try to ssh.
    # Just confirm the function can be imported and filter works.
    # (analyze_failed_tests_v5 calls ensure_on_branch which we won't run here
    # to avoid extra remote calls — INTEGRATION GAP #3 documented.)

    # Step 5: update_manifest
    handled = {"tests": []}
    updated_manifest = _MU.update_manifest(manifest, batch_results, handled)
    MANIFEST_PATH.write_text(
        json.dumps(updated_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[5] manifest updated -> {MANIFEST_PATH}")

    # Step 6: Final summary
    print("=" * 70)
    print("SMOKE SUMMARY")
    print("=" * 70)
    stats = batch_results.get("statistics", {})
    rl = batch_results.get("remote_log", {})
    print(f"  remote raw_log_path : {rl.get('raw_log_path')}")
    print(f"  summary.txt exists  : {summary_path.exists()} ({summary_path})")
    print(f"  batch_results exists: {batch_results_path.exists()}")
    print(f"  remote_log present  : {bool(rl) and bool(rl.get('raw_log_path'))}")
    print(f"  stats               : {stats}")

    last_batch_ids = [t.get("last_batch_id") for t in updated_manifest["tests"]]
    print(f"  last_batch_id set   : {all(b == BATCH_ID for b in last_batch_ids)}")
    print(f"  manifest stats      : {updated_manifest.get('statistics')}")

    # Determine PASS/FAIL
    n_passed = stats.get("passed", 0)
    n_total = stats.get("total", 0)
    if n_passed == n_total and n_total > 0:
        print(f"  PIPELINE: PASS — {n_passed}/{n_total} tests passed remotely")
    else:
        print(f"  PIPELINE: PARTIAL — {n_passed}/{n_total} passed; pipeline wiring OK")

    return 0


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
