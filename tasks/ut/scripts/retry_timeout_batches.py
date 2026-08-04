#!/usr/bin/env python3
"""并行重跑 timeout batches via bifrost.

策略: 每个 batch 起一个 execute_batch.py 子进程 (内部用 ThreadPoolExecutor
并行跑 batch 内测试, run_remote 走 bifrost), 外层用进程池控制并发度
(默认 8 = H20 空闲 GPU 数)。

用法:
  python3 retry_timeout_batches.py --run-dir runs/ut-20260718-164107 \
      --concurrency 8 [--limit 10] [--batch-list x.json]
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = PROJECT_ROOT / "runs" / "ut-20260718-164107"
# 环境: bifrost 后端 + HF 离线设置
ENV = {
    "BIFROST_CONFIG": "/gpfs/gcsp/liuxin/bifrost_test/settings.json",
    "REMOTE_BACKEND": "bifrost",
    "HF_HOME": "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub",
    "HF_HUB_CACHE": "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_CACHE": "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub",
    "HF_DATASETS_CACHE": "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/datasets",
}


def retry_one(bid: str, run_dir: str, wall_timeout: int = 300) -> dict:
    """重跑单个 batch, 返回结果摘要."""
    env = dict(os.environ)
    env.update(ENV)
    wf = str(Path(run_dir) / "workflow_state.json")
    exe = str(PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py")
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [sys.executable, exe, "--batch-config",
             str(Path(run_dir) / "batches" / bid / "batch_config.json"),
             "--workflow-state", wf, "--batch-id", bid,
             "--timeout", str(wall_timeout)],
            capture_output=True, text=True, timeout=wall_timeout + 1200, env=env,
        )
        elapsed = time.monotonic() - t0
        # 读更新后的 batch_results
        rp = Path(run_dir) / "batches" / bid / "batch_results.json"
        if rp.exists():
            rd = json.loads(rp.read_text())
            st = rd.get("statistics", {})
            return {
                "batch_id": bid, "rc": r.returncode, "elapsed": elapsed,
                "passed": st.get("passed", 0), "failed": st.get("failed", 0),
                "error": st.get("error", 0), "ignored": st.get("ignored", 0),
                "status": "done",
            }
        return {
            "batch_id": bid, "rc": r.returncode, "elapsed": elapsed,
            "status": "no_result", "stderr_tail": r.stderr[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"batch_id": bid, "status": "timeout", "elapsed": time.monotonic() - t0}
    except Exception as e:
        return {"batch_id": bid, "status": "error", "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=str(RUN_DIR))
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="只重跑前 N 个 batch (试点)")
    ap.add_argument("--timeout", type=int, default=600, help="每测试 watchdog 超时秒数 (默认 600)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    report = json.loads((run_dir / "phase2_stage1_report.json").read_text())
    batches = report["error_statistics"]["timeout"]["batch_list"]
    if args.limit:
        batches = batches[:args.limit]
    print(f"[retry] 重跑 {len(batches)} 个 timeout batch, 并发 {args.concurrency}, per-test timeout {args.timeout}s")

    results = []
    t_start = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(retry_one, b, str(run_dir), args.timeout): b for b in batches}
        done = 0
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            results.append(r)
            print(f"  [{done}/{len(batches)}] {r['batch_id']}: {r.get('status')} "
                  f"rc={r.get('rc')} p={r.get('passed','-')} f={r.get('failed','-')} "
                  f"e={r.get('error','-')} i={r.get('ignored','-')} {r.get('elapsed',0):.0f}s")
            # 增量保存
            (run_dir / "retry_timeout_progress.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=1))

    total = time.monotonic() - t_start
    # 汇总
    summary = {
        "total": len(batches),
        "elapsed_secs": total,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = run_dir / "retry_timeout_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n[retry] 完成 {len(batches)} batches in {total:.0f}s → {out}")
    # 打印汇总
    from collections import Counter
    statuses = Counter(r.get("status") for r in results)
    print(f"状态分布: {dict(statuses)}")
    passed_tests = sum(r.get("passed", 0) for r in results)
    failed_tests = sum(r.get("failed", 0) for r in results)
    print(f"重跑后: passed={passed_tests}, failed={failed_tests}")


if __name__ == "__main__":
    main()
