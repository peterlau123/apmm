#!/usr/bin/env python3
"""orchestrator_round.py - Kanban mode orchestrator (Stage 5 + Stage 2 per round)

Used ONLY in hermes-workflow with kanban.enabled=true.
Each round: reconcile previous batch results into test_load (v5 merge),
then select next batch, then create Kanban tasks.

Called by: ut-orchestrator Worker profile
"""

import json
import os
import sys
import importlib.util
from pathlib import Path

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parent.parent

sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from skills.ut.manifest_updater.scripts.update_status import merge_batch_results

# Hermes Kanban API
try:
    from hermes_cli.kanban_db import connect, create_task
except ImportError:
    connect = None
    create_task = None


def _load_batch_selector_fn(fn_name):
    """Load a function from batch-selector/scripts/generate_batch.py."""
    path = SKILL_DIR / "batch-selector" / "scripts" / "generate_batch.py"
    spec = importlib.util.spec_from_file_location("_generate_batch", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, fn_name)


def orchestrator_round(*, run_dir, workflow_state_path, prev_batch_dir,
                       batch_size, current_task_id=None):
    """Kanban ut-orchestrator round: Stage 5 (reconcile prev) then Stage 2 (select next).

    Operates on test_load (the working dataset), not manifest.json.

    Parameters
    ----------
    run_dir: Path-like, the workflow run directory
    workflow_state_path: Path-like, workflow_state.json (to find test_load path)
    prev_batch_dir: Path-like or None, previous batch directory for reconciliation
    batch_size: int, number of tests per batch
    current_task_id: str or None, the Kanban task ID that triggered this round

    Returns {"completed": bool, "next_batch": dict|None,
             "executor_task_id": str|None, "fixer_task_id": str|None,
             "next_orchestrator_task_id": str|None}.
    """
    select_batch = _load_batch_selector_fn("select_batch")
    write_batch_config = _load_batch_selector_fn("write_batch_config")

    run_dir = Path(run_dir)

    # Read test_load path from workflow_state
    state = json.loads(Path(workflow_state_path).read_text(encoding="utf-8"))
    test_load_path = Path(state["paths"]["test_load"])
    test_load = json.loads(test_load_path.read_text(encoding="utf-8"))

    # Stage 5: reconcile previous batch results into test_load (v5 merge)
    if prev_batch_dir is not None:
        br = Path(prev_batch_dir) / "batch_results.json"
        if br.exists():
            batch_results = json.loads(br.read_text(encoding="utf-8"))
            hp = Path(prev_batch_dir) / "handled_tests.json"
            handled = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {"tests": []}
            merge_batch_results(test_load, batch_results, handled)
            test_load_path.write_text(
                json.dumps(test_load, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    # Stage 2: select next batch from test_load
    selected = select_batch(test_load, batch_size)
    if not selected:
        return {"completed": True, "next_batch": None}

    nb = f"batch_{len(list(run_dir.glob('batch_*'))) + 1:04d}"
    nd = run_dir / nb
    nd.mkdir(exist_ok=True)
    cfg = write_batch_config(
        path=nd / "batch_config.json",
        batch_id=nb,
        iteration=0,
        run_id=run_dir.name,
        selected=selected,
    )

    # Hermes Kanban API: create executor, fixer, next orchestrator tasks
    executor_task_id = None
    fixer_task_id = None
    next_orchestrator_task_id = None

    if connect and create_task:
        try:
            conn = connect()
            executor_task_id = create_task(
                conn, title=f"execute-{nb}", assignee="ut-executor",
                parents=[current_task_id] if current_task_id else []
            )
            fixer_task_id = create_task(
                conn, title=f"failure-handle-{nb}", assignee="ut-fixer",
                parents=[executor_task_id]
            )
            next_orchestrator_task_id = create_task(
                conn, title=f"orchestrator-{len(list(run_dir.glob('batch_*'))) + 2:04d}",
                assignee="ut-batch-selector",
                parents=[fixer_task_id]
            )
        except Exception as e:
            print(f"[orchestrator_round] Kanban task creation failed: {e}")

    return {
        "completed": False, "next_batch": cfg,
        "executor_task_id": executor_task_id,
        "fixer_task_id": fixer_task_id,
        "next_orchestrator_task_id": next_orchestrator_task_id
    }
