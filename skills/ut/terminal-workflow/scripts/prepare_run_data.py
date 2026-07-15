#!/usr/bin/env python3
"""prepare_run_data.py - Step 3/5: prepare manifest, test_load, workflow_state"""
import argparse, json, shutil, subprocess, sys
from datetime import datetime, timezone; from pathlib import Path
P = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(P) not in sys.path: sys.path.insert(0, str(P))
from skills.ut.shared import load_workflow_yaml as lwy, validate_and_write as vaw

def main():
    a = argparse.ArgumentParser(); a.add_argument("--run-dir","-d",required=True)
    a.add_argument("--test-list","-t",default=None)
    a.add_argument("--manifest-source","-m",default=None)
    a.add_argument("--test-load-count","-c",type=int,default=None)
    a.add_argument("--mode",default="terminal",choices=["terminal","hermes"])
    o = a.parse_args(); rd = Path(o.run_dir)
    if not rd.exists(): print("[ERROR] run_dir not found",file=sys.stderr); sys.exit(1)
    wyp = rd / "workflow.yaml"
    if not wyp.exists(): print("[ERROR] workflow.yaml not found",file=sys.stderr); sys.exit(1)
    cfg = lwy(wyp); inf = cfg.get("input_filter",{}); cf = cfg.get("config",{})
    wf = cfg.get("workflow",{})
    tlp = Path(o.test_list) if o.test_list else None
    if not tlp and inf.get("test_list_path"): tlp = Path(inf["test_list_path"])
    msp = Path(o.manifest_source) if o.manifest_source else None
    if not msp and inf.get("manifest_source"): msp = Path(inf["manifest_source"])
    tlc = o.test_load_count or wf.get("test_load",{}).get("count",1000)
    mp = rd / "manifest.json"; tlr = None; tc = 0
    if msp:
        shutil.copy2(msp, mp)
        tc = len(json.loads(open(mp,encoding="utf-8").read()).get("tests",[]))
        print("[prepare] manifest copied:", tc, "tests")
    elif tlp:
        td = rd / "test_list.txt"; shutil.copy2(tlp, td)
        lines = [l.strip() for l in open(td,encoding="utf-8").read().splitlines()
                 if l.strip() and not l.startswith("#")]
        tests = [{"id":i+1,"test_node":n,
                  "test_file":n.split("::")[0] if "::" in n else n,
                  "test_name":n.split("::")[1] if "::" in n else "","status":"pending"}
                 for i,n in enumerate(lines)]
        m = {"version":"2.0","generated_at":datetime.now(timezone.utc).isoformat(),
             "source":"test_list_file","tests":tests,
             "statistics":{"total":len(tests),"pending":len(tests)}}
        vaw(m,"manifest",mp); tc = len(tests); tlr = td
        print("[prepare] manifest generated:", tc, "tests")
    else:
        print("[ERROR] manifest_source and test_list_path both missing",file=sys.stderr)
        sys.exit(1)
    now = datetime.now(timezone.utc).isoformat(); sp = rd / "workflow_state.json"
    sd = Path(__file__).parent.parent.parent
    s = {"workflow":{"name":wf.get("name","UT Test Workflow"),
         "version":wf.get("version","2.0"),
         "test_name":wf.get("test_name","ut"),"started_at":now,"status":"running"},
         "current_stage":"collect","iteration":0,
         "paths":{"run_dir":str(rd),"workflow_yaml":str(wyp),"manifest":str(mp),
                  "test_list":str(tlr) if tlr else None,
                  "manifest_schema":str(sd/"shared"/"manifest_schema.json"),
                  "batches_dir":str(rd/"batches"),"logs_dir":str(rd/"logs"),
                  "reports_dir":str(rd/"reports"),"workflow_state":str(sp)},
         "stats":{"total_tests":tc,"passed":0,"failed":0,"error":0,"ignored":0,
                  "pending":tc,"error_rate":0.0},
         "current_batch":{"batch_id":None,"size":0,"started_at":None},
         "flags":{"stop_requested":False,"pause_requested":False,
                  "pause_reason":None,"consecutive_failures":0},
         "last_update":now,
         "last_worker_result":{"stats":{"passed":0,"failed":0,"error":0,"ignored":0,"pending":0},
                               "next_action":"continue","error":None,"blocked_reason":None}}
    vaw(s,"workflow_state",sp); print("[prepare] workflow_state created")
    gs = P / "tasks" / "ut" / "scripts" / "generate_test_load.py"
    if gs.exists():
        r = subprocess.run([sys.executable,str(gs),"--manifest-path",str(mp),
            "--count",str(tlc),"--output-dir",str(rd),"--workflow-state",str(sp)],
            capture_output=True,text=True,timeout=60)
        if r.returncode == 0: print("[prepare] test_load generated")
        else: print("[WARN] generate_test_load.py:", r.stderr[:100])
    print("---"); print("run_dir:", rd); print("manifest:", mp)
    print("test_list:", tlr); print("workflow_state:", sp)
    print("total_tests:", tc); print("test_load_count:", tlc)
    print("batch_size:", cf.get("batch_size",8))
    print("execution_strategy:", wf.get("execution_strategy","single-phase"))
    print("resume_from:", cf.get("resume_from")); print("...")
if __name__ == "__main__": main()
