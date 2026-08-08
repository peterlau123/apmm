#!/usr/bin/env python3
"""重跑剩余 ignored (跳过 detokenize 模型类 — HF 下载卡死).

背景: 主跑 6,121 ignored (timeout 连坐) → retry_timeout_batches 重跑救回 3,392,
但卡在 detokenize 模型类 (codellama-7b/Pixtral 需 HF 下载, 无网络 → hang 超时).
本脚本: 只重跑非 detokenize 的 ignored (tool_choice/scheduler/attention 等可救).
"""
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path("/gpfs/gcsp/liuxin/apmm")
RUN_DIR = PROJECT_ROOT / "runs" / "ut-20260807-110322"
TL_PATH = sorted(RUN_DIR.glob("test_load_*.json"))[-1]
WS_PATH = RUN_DIR / "workflow_state.json"
BATCHES = RUN_DIR / "batches"
EXEC = PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py"
UPD = PROJECT_ROOT / "skills/ut/ut_common/update_test_load_two_phase.py"
ENV = {"REMOTE_BACKEND": "bifrost",
       "BIFROST_CONFIG": "/gpfs/gcsp/liuxin/bifrost_test/settings.json"}
SKIP_FILES = ("test_detokenize",)  # 模型类 (HF 下载卡死)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-only", default=None,
                    help="只重跑指定子串的测试 (如 test_detokenize), 默认跳过 SKIP_FILES")
    ap.add_argument("--prefix", default="ig",
                    help="batch 前缀 (避免多进程 batch 命名冲突, 默认 ig)")
    ap.add_argument("--max-batch-size", type=int, default=8,
                    help="每批测试数 (调大减少批间调度开销, 默认 8)")
    ap.add_argument("--status", default="ignored",
                    help="要重跑的状态 (ignored/error/failed, 默认 ignored)")
    args = ap.parse_args()
    tl = json.loads(TL_PATH.read_text())
    if args.include_only:
        targets = [t for t in tl["tests"] if t.get("status") == args.status
                   and args.include_only in (t.get("test_node") or "")]
        print(f"[rerun-ig] 目标: {len(targets)} 个 (status={args.status}, include={args.include_only})")
    else:
        targets = [t for t in tl["tests"] if t.get("status") == args.status
                   and not any(f in (t.get("test_node") or "") for f in SKIP_FILES)]
        print(f"[rerun-ig] 目标: {len(targets)} 个 (status={args.status})")
    if not targets:
        print("无目标")
        return

    groups = [targets[i:i + args.max_batch_size] for i in range(0, len(targets), args.max_batch_size)]
    print(f"[rerun-ig] 分 {len(groups)} 批 ({args.max_batch_size}/批, 顺序执行)")
    t0 = time.time()
    for gi, tests in enumerate(groups, 1):
        bid = f"batch_20260808_{args.prefix}_{gi:04d}"
        cfg_dir = BATCHES / bid
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = {"batch_id": bid, "batch_type": "normal", "tests": tests,
               "distributed_count": 0, "requires_multi_gpu": False,
               "gpu_per_test": 1, "generated_at": datetime.now().isoformat()}
        (cfg_dir / "batch_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
        r = subprocess.run(
            [sys.executable, str(EXEC), "--batch-config", str(cfg_dir / "batch_config.json"),
             "--workflow-state", str(WS_PATH), "--batch-id", bid, "--timeout", "3000"],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=900)
        brp = cfg_dir / "batch_results.json"
        if r.returncode != 0 or not brp.exists():
            print(f"  ✗ {bid}: rc={r.returncode} 超时900s (继续下一批)")
            continue
        subprocess.run(
            [sys.executable, str(UPD), "--workflow-state", str(WS_PATH),
             "--batch-id", bid, "--batch-results", str(brp)],
            capture_output=True, text=True, env={**__import__("os").environ, **ENV}, timeout=300)
        br = json.loads(brp.read_text())
        st = br.get("statistics", {})
        if gi % 25 == 0 or gi == len(groups):
            el = time.time() - t0
            tl2 = json.loads(TL_PATH.read_text())
            c = Counter(t["status"] for t in tl2["tests"])
            print(f"  [{gi}/{len(groups)}] {el/60:.0f}min | test_load p={c.get('passed')} "
                  f"ig={c.get('ignored')} | 本批 p={st.get('passed')}")
    tl2 = json.loads(TL_PATH.read_text())
    c = Counter(t["status"] for t in tl2["tests"])
    print(f"[rerun-ig] 完成 {len(groups)} 批 | {(time.time()-t0)/60:.0f}min | test_load: {dict(c)}")


if __name__ == "__main__":
    main()
