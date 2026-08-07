#!/usr/bin/env python3
"""重跑 test_load 里 marlin 相关 failed 用例 (算子修复后救回).

背景: _moe_C 扩展已重编译 (含 moe_wna16_marlin_gemm 注册) → 2,638 个
marlin failed 可重跑救回. 分批 execute_batch (bifrost) → 回写 test_load.
"""
import json
import subprocess
import sys
import time
from collections import Counter
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
        n = (t.get("test_node") or "").lower()
        m = (t.get("error_message") or "")
        # marlin 算子缺失类 (moe_wna16_marlin_gemm / batched marlin)
        if "moe_wna16_marlin_gemm" in m or ("marlin" in n and "moe" in n):
            targets.append(t)
    print(f"[rerun-marlin] 目标: {len(targets)} 个")
    if not targets:
        print("无目标")
        return

    groups = [targets[i:i + 8] for i in range(0, len(targets), 8)]
    print(f"[rerun-marlin] 分 {len(groups)} 批 (8/批)")
    passed = failed = 0
    t0 = time.time()
    for gi, tests in enumerate(groups, 1):
        bid = f"batch_20260807_marlin_{gi:04d}"
        cfg_dir = BATCHES / bid
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = {"batch_id": bid, "batch_type": "normal", "tests": tests,
               "distributed_count": 0, "requires_multi_gpu": False,
               "gpu_per_test": 1, "generated_at": datetime.now().isoformat()}
        (cfg_dir / "batch_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
        r = subprocess.run(
            [sys.executable, str(EXEC), "--batch-config", str(cfg_dir / "batch_config.json"),
             "--workflow-state", str(WS_PATH), "--batch-id", bid, "--timeout", "600"],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=1200)
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
        passed += st.get("passed", 0)
        failed += st.get("failed", 0)
        if gi % 20 == 0 or gi == len(groups):
            el = time.time() - t0
            print(f"  [{gi}/{len(groups)}] {el/60:.0f}min | 累计 p={passed} f={failed}")
    # 最终
    tl2 = json.loads(TL_PATH.read_text())
    c = Counter(t["status"] for t in tl2["tests"])
    print(f"[rerun-marlin] 完成 | 总耗时 {(time.time()-t0)/60:.0f}min")
    print(f"[rerun-marlin] test_load: {dict(c)}")


if __name__ == "__main__":
    main()
