"""resolver_gateway_runner.py — ut-dependency-resolver gateway main loop.

Subscribes to Kanban tasks with:
    final_status == "pending"
    resolution.action == "delegate_to_dependency_resolver"

For each claimed task:
    1. Read dependency_id / dependency_type from resolution.
    2. Call two_stage_sync.sync_model(...) (or install_package for type=package).
    3. Release with:
         - success → final_status="ready",       resolution.status="resolved"
         - failure → final_status="ignored",     resolution.status="failed_offline",
                      ignored_reason="offline_unfixable: <detail>"

Design constraints (postmortem §4.3.2):
  - Resolver promotes `ignored` directly (NEVER bounces back to fixer).
  - No per-task retry (executor's max_retry covers it).
  - 30-min hard budget per task; on timeout → ignored.
  - One claim at a time (Kanban gateway natural concurrency = 1).

This module is import-only. The actual `hermes kanban claim/release` CLI
wiring lives behind a thin `KanbanClient` Protocol so unit tests can supply
a fake. Production wiring is filled in once the Hermes Kanban CLI surface
stabilizes; until then `run_forever()` raises NotImplementedError if invoked
without a client.

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §4
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SCRIPT_DIR = Path(__file__).resolve().parent
TSS_PATH = SCRIPT_DIR / "two_stage_sync.py"

logger = logging.getLogger(__name__)


# ── Kanban client protocol (implementation supplied at wire-up) ──────────────


class KanbanClient(Protocol):
    """Minimal Kanban surface the resolver needs.

    Production impl will shell out to `hermes kanban …`; tests pass a fake.
    """

    def claim_pending_delegate(self) -> dict | None:
        ...

    def release_ready(self, task_id: str, resolution: dict) -> None:
        ...

    def release_ignored(self, task_id: str, resolution: dict, ignored_reason: str) -> None:
        ...


# ── Resolution helpers ────────────────────────────────────────────────────────


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("two_stage_sync", TSS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["two_stage_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class ResolveDecision:
    """What the runner decided about a single claimed task."""
    task_id: str
    action: str  # "release_ready" | "release_ignored"
    resolution: dict
    ignored_reason: str | None = None


def resolve_one(task: dict, sync_module=None) -> ResolveDecision:
    """Pure decision function — given a claimed task, return what to release.

    Separated from the polling loop so it's trivial to unit-test.
    """
    task_id = task["task_id"]
    res_in = task.get("resolution", {})
    dep_id = res_in.get("dependency_id")
    dep_type = res_in.get("dependency_type", "model")

    if not dep_id:
        # Malformed task — fixer should never have written this, but defend.
        return ResolveDecision(
            task_id=task_id, action="release_ignored",
            resolution={"status": "failed_offline",
                        "action": res_in.get("action"),
                        "dependency_id": None},
            ignored_reason="offline_unfixable: missing dependency_id",
        )

    if dep_type != "model":
        # Package handling is out of scope for M2 — fixer currently only
        # delegates model_missing failures. Defer with a clear reason.
        return ResolveDecision(
            task_id=task_id, action="release_ignored",
            resolution={"status": "failed_offline",
                        "action": res_in.get("action"),
                        "dependency_id": dep_id, "dependency_type": dep_type},
            ignored_reason=f"offline_unfixable: dependency_type={dep_type} not yet supported",
        )

    tss = sync_module or _load_sync_module()
    result = tss.sync_model(dep_id)

    if result.status == "resolved":
        return ResolveDecision(
            task_id=task_id, action="release_ready",
            resolution={"status": "resolved",
                        "action": res_in.get("action"),
                        "dependency_id": dep_id,
                        "dependency_type": dep_type,
                        "local_path": result.local_path},
        )

    # Any non-resolved status promotes to ignored.
    return ResolveDecision(
        task_id=task_id, action="release_ignored",
        resolution={"status": "failed_offline",
                    "action": res_in.get("action"),
                    "dependency_id": dep_id,
                    "dependency_type": dep_type,
                    "failure_status": result.status,
                    "failure_detail": result.detail},
        ignored_reason=f"offline_unfixable: {result.reason or result.status}",
    )


# ── Polling loop ──────────────────────────────────────────────────────────────


def run_one_iteration(client: KanbanClient, sync_module=None) -> ResolveDecision | None:
    """Claim a task (if any), resolve it, release. Returns the decision or None."""
    task = client.claim_pending_delegate()
    if task is None:
        return None

    decision = resolve_one(task, sync_module=sync_module)

    if decision.action == "release_ready":
        client.release_ready(decision.task_id, decision.resolution)
    else:
        client.release_ignored(decision.task_id, decision.resolution,
                               decision.ignored_reason or "offline_unfixable: unknown")
    return decision


def run_forever(client: KanbanClient,
                poll_interval_seconds: int = 10,
                sync_module=None) -> None:  # pragma: no cover — long-running
    """Run the resolver until the process is killed (Hermes gateway lifecycle)."""
    logger.info("ut-dependency-resolver gateway starting, poll=%ss", poll_interval_seconds)
    while True:
        try:
            decision = run_one_iteration(client, sync_module=sync_module)
            if decision is None:
                time.sleep(poll_interval_seconds)
                continue
            logger.info("resolved task %s → %s (reason=%s)",
                        decision.task_id, decision.action,
                        decision.ignored_reason or "ok")
        except Exception:
            logger.exception("resolver iteration crashed — backing off")
            time.sleep(poll_interval_seconds)


if __name__ == "__main__":  # pragma: no cover
    print("This module is intended to be imported by the Hermes gateway "
          "wrapper. Standalone run requires a KanbanClient implementation.")
    sys.exit(0)
