#!/usr/bin/env python3
"""phase2_stage1.py - Phase 2 Stage 1: Statistical analysis of Phase 1 results."""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from skills.ut.ut_common import get_paths

SUGGESTIONS = {
    "dependency": "Check environment, install missing dependencies",
    "network": "Retry, check network/proxy", "resource": "Check GPU/CPU/Memory",
    "version": "Update code for API changes", "functional": "Analyze test logic",
    "download_error": "Check model path/permissions/token",
    "oom": "Reduce batch size or use smaller model",
    "timeout": "Check complexity, increase timeout",
    "collection": "Check test defs and pytest config",
    "assertion": "Analyze expected vs actual output", "other": "Manual inspection required",
}
PRIORITIES = {
    "network": "P0", "oom": "P0", "timeout": "P0",
    "dependency": "P1", "resource": "P1", "version": "P1", "download_error": "P1",
    "functional": "P2", "collection": "P2", "assertion": "P2", "other": "P2",
}

def classify(tests, batch_id, stats):
    for t in tests:
        st = t.get("status", "pending")
        # ponytail: 旧版统计 failed+error+ignored,refactor 误删 ignored(F1 回归)。
        # ignored 多为 retriable timeout/oom 经 watchdog SIGKILL 后置位,正是 Phase 2 要捞出来重试的。
        if st not in ("failed", "error", "ignored"): continue
        et = t.get("error_type") or "other"
        if et not in stats:
            stats[et] = {"test_count": 0, "batch_count": 0, "batch_list": [], "test_list": [],
                         "affected_test_files": [], "suggestion": SUGGESTIONS.get(et, "Manual"),
                         "priority": PRIORITIES.get(et, "P2")}
        stats[et]["test_count"] += 1
        if batch_id not in stats[et]["batch_list"]:
            stats[et]["batch_count"] += 1; stats[et]["batch_list"].append(batch_id)
        stats[et]["test_list"].append(t.get("test_node", ""))
        tf = t.get("test_file", "")
        if tf and tf not in stats[et]["affected_test_files"]: stats[et]["affected_test_files"].append(tf)

def gen_md(r):
    lines = ["# Phase 2 Stage 1: Statistical Analysis Report", "",
        f"**Generated:** {r['generated_at']}", f"**Run dir:** {r['meta'].get('run_dir','N/A')}",
        f"**Total batches:** {r['meta'].get('total_batches',0)}", "",
        "## Overview", "",
        f"- Failed/error tests: {r['summary']['total_failed_tests']}",
        f"- Error type categories: {r['summary']['error_type_count']}", "",
        "### Priority Distribution", ""]
    for p,l in [("P0","Immediate"),("P1","High"),("P2","Medium")]:
        lines.append(f"- **{p} ({l})**: {r['summary']['priority_breakdown'].get(p,0)} type(s)")
    lines.extend(["", "## Error Type Details", ""])
    for et,s in sorted(r['error_statistics'].items(), key=lambda x: (x[1].get("priority","P2"),-x[1]["test_count"])):
        lines.extend([f"### {et} ({s.get('priority','P2')})", "",
            f"- Tests: {s['test_count']}, Batches: {s['batch_count']}, Files: {len(s['affected_test_files'])}",
            "", "**Suggestion:**", f"{s.get('suggestion','N/A')}", "", "**Batches:**", ""])
        for b in s["batch_list"]: lines.append(f"- `{b}`")
        lines.extend(["", "**Test Files:**", ""])
        for f in s["affected_test_files"]: lines.append(f"- `{f}`")
        lines.append("")
    lines.extend(["## Next Step", "", "Write `user_decision.json` in run dir:", "1. Retry by error type", "2. Retry specific batches", "3. Skip all"])
    return "\n".join(lines)

def main():
    p = argparse.ArgumentParser(description="Phase 2 Stage 1: Statistical analysis")
    p.add_argument("--run-dir","-d",required=True); p.add_argument("--output-dir","-o",default=None)
    a = p.parse_args()
    run_dir = Path(a.run_dir)
    if not run_dir.exists(): sys.exit(f"[ERROR] run_dir not found: {run_dir}")
    out_dir = Path(a.output_dir) if a.output_dir else run_dir
    paths = get_paths(run_dir / "workflow_state.json")
    tl_path = paths.get("test_load", "")
    if not tl_path or not Path(tl_path).exists(): sys.exit("[ERROR] test_load not found")
    tl = json.loads(Path(tl_path).read_text(encoding="utf-8"))
    batch_ids = sorted([d.name for d in (run_dir/"batches").iterdir() if d.is_dir()]) if (run_dir/"batches").exists() else []
    stats = {}
    for bid in batch_ids:
        bt = [t for t in tl.get("tests",[]) if t.get("last_batch_id")==bid]
        if not bt: continue  # ponytail: 空 batch 不兜底,避免把全部非 pending 测试归到自己名下双计数(F2)
        classify(bt, bid, stats)
    meta = {"run_dir":str(run_dir),"test_load_path":str(tl_path),"total_batches":len(batch_ids),"total_tests":len(tl.get("tests",[]))}
    total = sum(s["test_count"] for s in stats.values())
    p0 = sum(1 for s in stats.values() if s["priority"]=="P0")
    p1 = sum(1 for s in stats.values() if s["priority"]=="P1")
    p2 = sum(1 for s in stats.values() if s["priority"]=="P2")
    report = {"stage":"phase2_stage1","generated_at":datetime.now(timezone.utc).isoformat(),"meta":meta,
              "error_statistics":stats,"summary":{"total_failed_tests":total,"error_type_count":len(stats),
              "priority_breakdown":{"P0":p0,"P1":p1,"P2":p2}}}
    (out_dir/"phase2_stage1_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    (out_dir/"phase2_stage1_report.md").write_text(gen_md(report),encoding="utf-8")
    print(f"[OK] Reports in {out_dir}")
    for et,s in sorted(stats.items(),key=lambda x:-x[1]["test_count"]):
        print(f"  {et} ({s['priority']}): {s['test_count']} tests, {s['batch_count']} batches")
    print(json.dumps({"stage":"phase2_stage1_complete","next_action":"wait","reason":"Await human decision"}))

if __name__=="__main__": main()
