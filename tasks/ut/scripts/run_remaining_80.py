#!/usr/bin/env python3
"""补跑 test_load 剩余 80 条 block_fp8 (旧 cuda:1 batch 占用名额导致未选中).

流程: 读 test_load pending → 分 10 组 (8/组) → 写 batch_config →
execute_batch (bifrost) → update_test_load_two_phase 回写 → 验证.
"""
import json
import subprocess
import sys
import time
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
    pend = [t for t in tl["tests"] if t.get("status") == "pending"]
    print(f"[run-80] test_load pending: {len(pend)}")
    if not pend:
        print("[run-80] 无 pending, 无需补跑")
        return
    if len(pend) > 80:
        print(f"[run-80] WARN: pending {len(pend)} > 80, 只处理前 80 条")
        pend = pend[:80]

    groups = [pend[i:i + 8] for i in range(0, len(pend), 8)]
    ok = 0
    for gi, tests in enumerate(groups, 1):
        bid = f"batch_20260806_r80_{gi:02d}"
        cfg_dir = BATCHES / bid
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "batch_id": bid, "batch_type": "normal", "tests": tests,
            "distributed_count": 0, "requires_multi_gpu": False,
            "gpu_per_test": 1, "generated_at": datetime.now().isoformat(),
        }
        (cfg_dir / "batch_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
        print(f"\n[Batch {gi}/{len(groups)}] {bid} ({len(tests)} tests)")

        # execute
        r = subprocess.run(
            [sys.executable, str(EXEC), "--batch-config", str(cfg_dir / "batch_config.json"),
             "--workflow-state", str(WS_PATH), "--batch-id", bid, "--timeout", "600"],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=1200)
        if r.returncode != 0:
            print(f"  ✗ execute_batch rc={r.returncode}: {r.stderr[-300:]}")
            continue
        brp = cfg_dir / "batch_results.json"
        if not brp.exists():
            print(f"  ✗ batch_results.json 不存在")
            continue

        # 回写 test_load
        u = subprocess.run(
            [sys.executable, str(UPD), "--workflow-state", str(WS_PATH),
             "--batch-id", bid, "--batch-results", str(brp)],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=300)
        if u.returncode != 0:
            print(f"  ✗ update_test_load rc={u.returncode}: {u.stderr[-200:]}")
            continue
        # 统计本批结果
        br = json.loads(brp.read_text())
        st = br.get("statistics", {})
        print(f"  ✓ done: p={st.get('passed')} f={st.get('failed')} ig={st.get('ignored')}")
        ok += 1

    # 最终验证
    tl2 = json.loads(TL_PATH.read_text())
    from collections import Counter
    c = Counter(t["status"] for t in tl2["tests"])
    print(f"\n[run-80] 补跑完成 {ok}/{len(groups)} 组 | test_load: {dict(c)}")


if __name__ == "__main__":
    main()
