#!/usr/bin/env python3"""create_run_dir.py - Step 1/5: create run dir + copy workflow.yaml"""
import argparse, json, shutil, sys
from datetime import datetime, timezone; from pathlib import Path
P = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(P) not in sys.path: sys.path.insert(0, str(P))
from skills.ut.shared import create_run_dir as scrd, load_workflow_yaml as lwy

def main():
    a = argparse.ArgumentParser(); a.add_argument("--workflow-yaml","-y",required=True)
    a.add_argument("--mode",default="terminal",choices=["terminal","hermes"])
    o = a.parse_args(); sy = Path(o.workflow_yaml)
    if not sy.exists(): print("[ERROR] workflow.yaml not found",file=sys.stderr); sys.exit(1)
    c = lwy(sy); tn = c.get("workflow",{}).get("test_name","ut")
    rd = scrd(test_name=tn, workflow_yaml_path=sy)
    ty = rd / "workflow.yaml"; shutil.copy2(sy, ty)
    for d in ["batches","logs","reports"]: (rd / d).mkdir(exist_ok=True)
    agents_dir = P / ".agents"; agents_dir.mkdir(parents=True, exist_ok=True)
    pf = agents_dir / "current_run.json"
    open(pf,"w").write(json.dumps({"run_dir":str(rd),"workflow_yaml_path":str(ty),
        "started_at":datetime.now(timezone.utc).isoformat()},indent=2))
    print("[terminal] run_dir ready:", rd)
    wf = c.get("workflow",{}); inf = c.get("input_filter",{}); cfg = c.get("config",{})
    print("---"); print("run_dir:", rd); print("params:")
    items = [("test_list_path", inf.get("test_list_path")),
        ("manifest_source", inf.get("manifest_source")),
        ("execution_strategy", wf.get("execution_strategy","single-phase")),
        ("test_load_count", wf.get("test_load",{}).get("count",1000)),
        ("batch_size", cfg.get("batch_size",8)),
        ("max_retry", cfg.get("max_retry_per_test",3)),
        ("resume_from", cfg.get("resume_from"))]
    for k, v in items: print(" ", k, ":", v)
    print("...")
if __name__ == "__main__": main()
