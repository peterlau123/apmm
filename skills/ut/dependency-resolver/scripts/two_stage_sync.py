"""two_stage_sync.py — bring a model from t_ascend (online) to t_h20 (offline).

Strategy
--------
The cluster already exposes a shared GPFS path (HF_HUB_PATH below) that is
mounted on BOTH t_ascend (online) and t_h20 (offline test host). The
"two-stage" in the design name therefore collapses to:

  Stage 1: trigger `huggingface-cli download` on t_ascend → writes to GPFS
  Stage 2: verify the path is resolvable from t_h20 (sanity check, fast)

No physical second transfer is needed when GPFS is shared. If a future
deployment splits the storage, replace `_verify_on_t_h20` with an actual
`agent.py download` + `agent.py upload` chain — the call sites stay the same.

Failure semantics (per postmortem §4.3.2):
  - 30-min hard budget on the whole sync (download + verify)
  - On any failure → caller promotes the task to `ignored` (NOT retried,
    NOT bounced back to fixer)
  - SSH probe failure (network unreachable) surfaces as a distinct reason
    so the resolver can log it without spinning further

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §4
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parent.parent.parent
AGENT_PY = PROJECT_ROOT / "tools" / "agent.py"
DOWNLOAD_MODEL_PY = SCRIPT_DIR / "download_model.py"

DEFAULT_BUDGET_SECONDS = 30 * 60          # 30-min hard cap, per design §4.3.2
DEFAULT_SSH_PROBE_SECONDS = 30            # short network probe, per design §4.3.2

# Shared GPFS path — must match HF_HUB_PATH in download_model.py.
HF_HUB_PATH = "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"


SyncStatus = Literal["resolved", "failed_offline", "timeout", "auth_failed",
                     "network_unreachable", "disk_full"]


@dataclass
class SyncResult:
    status: SyncStatus
    model: str
    local_path: str | None = None
    reason: str | None = None
    # Detail captured for the kanban release payload — NEVER include secrets here.
    detail: str | None = None

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "model": self.model,
            "local_path": self.local_path,
            "reason": self.reason,
            "detail": self.detail,
        }


# ── Internal helpers (thin wrappers around agent.py + download_model.py) ──────


def _run_agent(profile: str, command: str, timeout: int) -> subprocess.CompletedProcess:
    """Run `agent.py -p <profile> run <command>` with a hard timeout.

    Separated for ease of monkeypatching in unit tests.
    """
    return subprocess.run(
        [sys.executable, str(AGENT_PY), "-p", profile, "run",
         "--timeout", str(timeout), command],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout + 30,
    )


def _probe_ssh(profile: str, probe_seconds: int = DEFAULT_SSH_PROBE_SECONDS) -> bool:
    """Fast SSH probe — returns False on network_unreachable."""
    try:
        r = _run_agent(profile, "true", probe_seconds)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False


def _download_on_t_ascend(model: str, budget_seconds: int) -> dict:
    """Call download_model.download_model() in-process.

    Returns the dict the downstream module produces: {status, model, ...}.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("download_model", DOWNLOAD_MODEL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.download_model(model, timeout=budget_seconds)


def _verify_on_t_h20(model: str, probe_seconds: int = DEFAULT_SSH_PROBE_SECONDS) -> bool:
    """Verify the downloaded model dir is visible on t_h20."""
    local_name = model.replace("/", "--")
    model_dir = f"{HF_HUB_PATH}/{local_name}"
    try:
        r = _run_agent("t_h20", f"test -d {model_dir} && echo OK || echo MISSING",
                       probe_seconds)
        return r.returncode == 0 and "OK" in (r.stdout or "")
    except subprocess.TimeoutExpired:
        return False


# ── Public entry ──────────────────────────────────────────────────────────────


def sync_model(model: str,
               budget_seconds: int = DEFAULT_BUDGET_SECONDS,
               probe_seconds: int = DEFAULT_SSH_PROBE_SECONDS) -> SyncResult:
    """Bring `model` from t_ascend's HF cache to t_h20-visible GPFS.

    Returns a SyncResult — caller is responsible for the kanban release.
    Never raises; all failures funnel into SyncResult.status.
    """
    if not _probe_ssh("t_ascend", probe_seconds):
        return SyncResult(status="network_unreachable", model=model,
                          reason="t_ascend SSH probe failed",
                          detail=f"agent.py -p t_ascend run `true` did not return within {probe_seconds}s")

    try:
        d = _download_on_t_ascend(model, budget_seconds)
    except subprocess.TimeoutExpired:
        return SyncResult(status="timeout", model=model,
                          reason=f"download budget {budget_seconds}s exceeded")

    status = d.get("status")
    if status == "timeout":
        return SyncResult(status="timeout", model=model,
                          reason=d.get("error") or "download timeout")
    if status != "success":
        err = (d.get("error") or "")[:300]
        if "401" in err or "403" in err or "auth" in err.lower() or "gated" in err.lower():
            return SyncResult(status="auth_failed", model=model,
                              reason="hf_auth_failed", detail=err)
        if "No space" in err or "disk" in err.lower():
            return SyncResult(status="disk_full", model=model,
                              reason="disk_full", detail=err)
        return SyncResult(status="failed_offline", model=model,
                          reason="download_failed", detail=err)

    local_path = d.get("path")

    if not _verify_on_t_h20(model, probe_seconds):
        return SyncResult(status="failed_offline", model=model,
                          local_path=local_path,
                          reason="t_h20 cannot see the model dir",
                          detail=f"`test -d {local_path}` on t_h20 failed")

    return SyncResult(status="resolved", model=model, local_path=local_path)


def main():  # pragma: no cover
    import argparse
    p = argparse.ArgumentParser(description="Sync HF model from t_ascend to t_h20")
    p.add_argument("--model", required=True)
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET_SECONDS)
    args = p.parse_args()
    res = sync_model(args.model, budget_seconds=args.budget)
    print(json.dumps(res.to_json(), indent=2, ensure_ascii=False))
    sys.exit(0 if res.status == "resolved" else 1)


if __name__ == "__main__":
    main()
