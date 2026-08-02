#!/usr/bin/env python3
"""phase2_stage2.py - Phase 2 Stage 2: Retry failed batches after human decision."""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))


def load_decision(path):
    if not path.exists():
        sys.exit(f"[ERROR] user_decision.json not found: {path}")
    d = json.loads(path.read_text(encoding="utf-8"))
    m = d.get("decision_method")
    if not m:
        sys.exit("[ERROR] Missing 'decision_method'")
    if m == "skip_all":
        print("[INFO] skip_all - ending workflow")
        sys.exit(0)
    if m not in ("retry_error_types", "retry_specific_batches", "retry_all"):
        sys.exit(f"[ERROR] Unknown method: {m}")
    return d


def determine_batches(decision, report):
    batches = []
    m = decision["decision_method"]
    if m == "retry_error_types":
        for et in decision.get("retry_error_types", []):
            batches.extend(report.get("error_statistics", {}).get(et, {}).get("batch_list", []))
    elif m == "retry_specific_batches":
        batches.extend(decision.get("retry_specific_batches", []))
    elif m == "retry_all":
        for s in report.get("error_statistics", {}).values():
            batches.extend(s.get("batch_list", []))
    return list(set(batches))


def _refresh_stats(wf_path: Path):
    """F4: Tally test_load stats into workflow_state after each retry."""
    if not wf_path.exists():
        return
    state = json.loads(wf_path.read_text(encoding="utf-8"))
    tl_path = state.get("paths", {}).get("test_load", "")
    if not tl_path:
        return
    tl = Path(tl_path)
    if not tl.is_absolute():
        tl = wf_path.parent / tl
    if not tl.exists():
        return
    test_load = json.loads(tl.read_text(encoding="utf-8"))
    stats = {}
    for t in test_load.get("tests", []):
        st = t.get("status", "pending")
        stats[st] = stats.get(st, 0) + 1
    state["stats"] = {
        "total_tests": len(test_load.get("tests", [])),
        "passed": stats.get("passed", 0),
        "failed": stats.get("failed", 0),
        "error": stats.get("error", 0),
        "ignored": stats.get("ignored", 0),
        "pending": stats.get("pending", 0),
        "error_rate": 0.0,
    }
    state["test_load_stats"] = stats
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    wf_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="Phase 2 Stage 2: Retry batches")
    p.add_argument("--run-dir", "-d", required=True)
    p.add_argument("--user-decision", "-u", default=None)
    p.add_argument("--stage1-report", "-r", default=None)
    p.add_argument("--output-dir", "-o", default=None)
    a = p.parse_args()

    run_dir = Path(a.run_dir)
    if not run_dir.exists():
        sys.exit("[ERROR] run_dir not found")
    ud = Path(a.user_decision) if a.user_decision else run_dir / "user_decision.json"
    rp = Path(a.stage1_report) if a.stage1_report else run_dir / "phase2_stage1_report.json"
    out = Path(a.output_dir) if a.output_dir else run_dir

    decision = load_decision(ud)
    if not rp.exists():
        sys.exit("[ERROR] stage1 report not found")
    s1 = json.loads(rp.read_text(encoding="utf-8"))
    batches = determine_batches(decision, s1)
    if not batches:
        print("[INFO] No batches to retry")
        sys.exit(0)

    print(f"[Stage 2] Retrying {len(batches)} batch(es): {batches}")
    wf = run_dir / "workflow_state.json"
    results = []
    for bid in batches:
        print(f"  Retrying {bid}...")
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py"),
             "--batch-id", bid, "--workflow-state", str(wf)],
            capture_output=True, text=True)
        bd = run_dir / "batches" / bid
        rp2 = bd / "batch_results.json"
        if not rp2.exists():
            results.append({"batch_id": bid, "status": "failed", "reason": "No batch_results.json"})
            continue
        ur = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "skills/ut/ut_common/update_test_load_two_phase.py"),
             "--batch-id", bid, "--batch-results", str(rp2), "--workflow-state", str(wf)],
            capture_output=True, text=True)
        if ur.returncode != 0:
            results.append({"batch_id": bid, "status": "failed", "reason": "test_load update failed"})
            continue
        # F4: Refresh test_load stats into workflow_state after each retry
        _refresh_stats(wf)
        rd = json.loads(rp2.read_text(encoding="utf-8"))
        st = rd.get("stats", {})
        results.append({"batch_id": bid, "status": "success",
                        "tests_passed": st.get("passed", 0), "tests_failed": st.get("failed", 0)})
        print(f"  OK {bid}")

    # F4: Final stats refresh after all retries
    _refresh_stats(wf)

    report = {
        "stage": "phase2_stage2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_retries": len(results),
        "batch_results": results,
        "summary_stats": {
            "total_passed": sum(r.get("tests_passed", 0) for r in results),
            "total_failed": sum(r.get("tests_failed", 0) for r in results),
        },
    }
    (out / "phase2_stage2_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Report: {out / 'phase2_stage2_report.json'}")
    ok = sum(1 for r in results if r["status"] == "success")
    print(f"Retries: {len(results)} total, {ok} success, {len(results) - ok} failed")
    print(json.dumps({
        "stage": "phase2_stage2_complete",
        "stats": report["summary_stats"],
        "next_action": "continue",
        "report_path": str(out / "phase2_stage2_report.json"),
    }))


if __name__ == "__main__":
    main()
