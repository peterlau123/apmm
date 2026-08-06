#!/usr/bin/env python3
"""重跑 flaky 测试 (ProcessRaisedException 2 个, 时序敏感可救).

用法: python3 rerun_flaky.py
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path("/gpfs/gcsp/liuxin/apmm")
RUN_DIR = PROJECT_ROOT / "runs" / "ut-20260806-103121"
TL_PATH = RUN_DIR / "test_load_8000_20260806_104353.json"
WS_PATH = RUN_DIR / "workflow_state.json"
BATCHES = RUN_DIR / "batches"
EXEC = PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py"
UPD = PROJECT_ROOT / "skills/ut/ut_common/update_test_load_two_phase.py"
ENV = {"REMOTE_BACKEND": "bifrost",
       "BIFROST_CONFIG": "/gpfs/gcsp/liuxin/bifrost_test/settings.json"}


def main():
    tl = json.loads(TL_PATH.read_text())
    targets = []
    for t in tl["tests"]:
        if t.get("status") != "failed":
            continue
        if "ProcessRaisedException" in (t.get("error_message") or ""):
            targets.append(t)
    print(f"[rerun-flaky] 目标: {len(targets)} 个")
    if not targets:
        return
    # 构造 batch (每个测试一个 batch, 避免一个挂全组挂)
    for i, t in enumerate(targets, 1):
        bid = f"batch_20260806_flaky_{i:02d}"
        cfg_dir = BATCHES / bid
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = {"batch_id": bid, "batch_type": "normal", "tests": [t],
               "distributed_count": 0, "requires_multi_gpu": False,
               "gpu_per_test": 1, "generated_at": datetime.now().isoformat()}
        (cfg_dir / "batch_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
        r = subprocess.run(
            [sys.executable, str(EXEC), "--batch-config", str(cfg_dir / "batch_config.json"),
             "--workflow-state", str(WS_PATH), "--batch-id", bid, "--timeout", "900"],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=1500)
        brp = cfg_dir / "batch_results.json"
        if r.returncode != 0 or not brp.exists():
            print(f"  ✗ {bid}: rc={r.returncode}")
            continue
        u = subprocess.run(
            [sys.executable, str(UPD), "--workflow-state", str(WS_PATH),
             "--batch-id", bid, "--batch-results", str(brp)],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=300)
        br = json.loads(brp.read_text())
        st = br.get("statistics", {})
        print(f"  ✓ {bid}: p={st.get('passed')} f={st.get('failed')}")
    # 汇总
    from collections import Counter
    tl2 = json.loads(TL_PATH.read_text())
    c = Counter(t["status"] for t in tl2["tests"])
    print(f"[rerun-flaky] 完成 | test_load: {dict(c)}")


if __name__ == "__main__":
    main()
