#!/usr/bin/env python3
"""run_linear_channel.py - drive the ut/workflow LINEAR channel end-to-end.

This is the agent-driven linear supervisor channel (skills/ut/workflow) expressed
as a turnkey loop: it wires the four real Worker stage scripts through the
loop_core linear algorithm and emits one-way Feishu progress cards each round —
exactly the channel contract (no Kanban, no state machine, manual Bastion).

Stages per round (loop_core linear algorithm):
  terminal-check -> Stage2 batch-selector -> Stage3 unit-test-executor (remote)
  -> Stage4 failure-handler -> Stage5 manifest-updater -> Feishu checkpoint

Usage:
  python tests/ut/integration/run_linear_channel.py \
      --workflow-yaml tests/ut/integration/fixtures/workflow.linear.yaml
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_BS = _load("lc_generate_batch", "skills/ut/batch-selector/scripts/generate_batch.py")
_EXEC = _load("lc_execute_batch", "skills/ut/unit-test-executor/scripts/execute_batch.py")
_MU = _load("lc_update_manifest", "skills/ut/manifest-updater/scripts/update_manifest.py")
_FH = _load("lc_analyze_failures", "skills/ut/failure-handler/scripts/analyze_failures.py")
_HR = _load("lc_hermes_runner", "skills/ut/terminal-workflow/scripts/hermes_runner.py")

from skills.ut.shared.validate_schema import validate_manifest  # noqa: E402

RUN_ID = "ut-linear"
MAX_ITERS = 12  # safety cap; retry subset should converge in <= max_retry+1 rounds


def _build_manifest(test_nodes: list[str]) -> dict:
    tests = []
    for i, node in enumerate(test_nodes, start=1):
        f, _, name = node.partition("::")
        tests.append({
            "id": i, "test_id": i, "test_node": node, "test_file": f,
            "test_name": name, "status": "pending", "retry_count": 0,
            "max_retry": 3, "last_batch_id": None,
        })
    return {
        "version": "2.0", "generated_at": "2026-06-21T00:00:00Z", "source": "linear-channel",
        "tests": tests,
        "statistics": {"total": len(tests), "passed": 0, "failed": 0, "error": 0,
                       "pending": len(tests), "executed": 0, "progress": 0.0},
    }


def _recalc_stats(manifest: dict) -> dict:
    tests = manifest.get("tests", [])
    by = {}
    for t in tests:
        by[t["status"]] = by.get(t["status"], 0) + 1
    total = len(tests)
    passed = by.get("passed", 0)
    manifest["statistics"] = {
        "total": total,
        "passed": passed,
        "failed": by.get("failed", 0),
        "error": by.get("error", 0) + by.get("retriable_error", 0),
        "pending": by.get("pending", 0) + by.get("fixed_pending_verify", 0),
        "ignored": by.get("ignored", 0),
        "executed": total - by.get("pending", 0),
        "progress": round(passed / total * 100, 1) if total else 0.0,
    }
    return manifest["statistics"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Drive ut/workflow linear channel")
    ap.add_argument("--workflow-yaml",
                    default="tests/ut/integration/fixtures/workflow.linear.yaml")
    args = ap.parse_args()

    wf_path = (_PROJECT_ROOT / args.workflow_yaml) if not Path(args.workflow_yaml).is_absolute() \
        else Path(args.workflow_yaml)
    cfg = yaml.safe_load(wf_path.read_text(encoding="utf-8"))

    # Startup §3: validate config — linear channel disallows kanban.enabled=true
    ok, missing = _HR.validate_required_config(cfg, channel="linear")
    if not ok:
        print(f"[linear] config invalid, missing: {missing}")
        return 1

    if cfg.get("kanban", {}).get("enabled"):
        print("[linear] ERROR: kanban.enabled=true — use the hermes-workflow channel for Kanban.")
        return 1

    # init run dir + state
    run_dir, state_path, state, iteration = _HR.init_or_resume(str(wf_path), None)
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"

    # Stage 1 (collect): ensure manifest has tests; build from test_list if not.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if not manifest.get("tests"):
        tl = cfg["input_filter"]["test_list_path"]
        tl_path = Path(tl) if Path(tl).is_absolute() else (_PROJECT_ROOT / tl)
        nodes = [ln.strip() for ln in tl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        manifest = _build_manifest(nodes)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    validate_manifest(manifest)

    feishu = _HR._setup_feishu()
    batch_size = int(cfg["config"].get("batch_size", 3))
    exec_cfg = _HR.get_execute_config(state_path)
    print(f"[linear] run_dir={run_dir}  batch_size={batch_size}  tests={len(manifest['tests'])}")
    print(f"[linear] exec_cfg={exec_cfg}")

    # ── loop_core linear algorithm ──────────────────────────────────────────────
    for iteration in range(1, MAX_ITERS + 1):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Stage 2 — batch-selector
        selected = _BS.select_batch(manifest, batch_size=batch_size)
        if not selected:
            print(f"[linear] iter {iteration}: no selectable tests — terminal.")
            break

        batch_id = f"batch_{iteration:03d}"
        batch_dir = run_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_config_path = batch_dir / "batch_config.json"
        _BS.write_batch_config(path=batch_config_path, batch_id=batch_id,
                               iteration=iteration, run_id=RUN_ID, selected=selected)
        print(f"\n[linear] iter {iteration}: selected {len(selected)} -> {batch_id}")

        # Stage 3 — unit-test-executor (REAL remote)
        summary = _EXEC.execute_batch(batch_config_path, state_path, exec_config=exec_cfg)
        if isinstance(summary, dict) and summary.get("next_action") == "wait":
            # handle_bastion_disconnect (linear: alert + stop, manual re-auth)
            reason = summary.get("blocked_reason", "bastion wait")
            print(f"[linear] BASTION DISCONNECT: {reason} — stopping (manual re-auth needed)")
            _HR.send_feishu_card(feishu, "alert", manifest, iteration,
                                 batch_id=batch_id, reason=reason, mode="linear")
            return 2
        br_path = Path(summary.get("batch_results_path", batch_dir / "batch_results.json"))
        full = json.loads(br_path.read_text(encoding="utf-8")) if br_path.exists() else summary

        # Stage 4 — failure-handler (offline download/network = retriable, no remote fix)
        handled = {"tests": []}
        try:
            _FH.filter_processable(full.get("tests", []))
        except Exception as e:
            print(f"[linear] failure-handler note: {e}")

        # Stage 5 — manifest-updater
        manifest = _MU.update_manifest(manifest, full, handled)
        _recalc_stats(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        st = manifest["statistics"]
        print(f"[linear] iter {iteration} done: passed={st['passed']} failed={st['failed']} "
              f"error={st['error']} pending={st['pending']} ignored={st.get('ignored', 0)}")

        # Checkpoint — one-way Feishu progress card
        _HR.send_feishu_card(feishu, "progress", manifest, iteration,
                             batch_id=batch_id, mode="linear")

        # terminal check
        if st["pending"] == 0:
            print(f"[linear] iter {iteration}: pending==0 — completed.")
            break
    else:
        print(f"[linear] hit MAX_ITERS={MAX_ITERS} safety cap.")

    final = manifest["statistics"]
    _HR.send_feishu_card(feishu, "complete", manifest, iteration, mode="linear")
    out = run_dir / "linear_channel_results.json"
    out.write_text(json.dumps({"iterations": iteration, "statistics": final,
                               "run_dir": str(run_dir)}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"[linear] DONE iterations={iteration} stats={final}")
    print(f"[linear] results -> {out}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
