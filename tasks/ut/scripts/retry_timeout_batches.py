#!/usr/bin/env python3
"""重跑 timeout batches via bifrost（合并 batch 模式, 2026-08-04 v3）。

策略 (v3, 用户指示): 不搞多个 execute_batch 进程并发 —— 多进程各自探测
GPU 会争抢同一批空闲卡 (实测 2 并发即互相踩踏 → 任务洪峰 → daemon 队列
饿死超时)。改为:
  1. 收集所有 timeout batch 的 tests, 按原 batch 归属记录 test_id → batch_id
  2. 攒成 super-batch: 每 max_batch_size (默认 8) 个测试一组, 生成合并 config
  3. 单进程串行跑每个 super-batch (execute_batch 内部 ThreadPoolExecutor
     按空闲 GPU 并行, 单进程探测无争抢)
  4. 跑完按 test id 拆回各原 batch 的 batch_results.json, 逐个回写 test_load

用法:
  python3 retry_timeout_batches.py --run-dir runs/ut-20260718-164107 \
      [--max-batch-size 8] [--limit 10] [--timeout 600]
"""
import argparse, json, os, subprocess, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
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


def run_super_batch(super_id: str, tests: list, run_dir: str, wall_timeout: int,
                    batch_type: str, gpu_per_test: int) -> dict:
    """跑一个合并 batch (单 execute_batch 进程), 返回 execute_batch 结果. """
    env = dict(os.environ)
    env.update(ENV)
    wf = str(Path(run_dir) / "workflow_state.json")
    exe = str(PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py")

    # 合并 batch 的临时 config (放 run_dir 下, 不污染 batches/)
    tmp_dir = Path(run_dir) / ".superbatches"
    tmp_dir.mkdir(exist_ok=True)
    cfg_path = tmp_dir / f"{super_id}_config.json"
    cfg_path.write_text(json.dumps({
        "batch_id": super_id,
        "batch_type": batch_type,
        "tests": tests,
        "distributed_count": sum(1 for t in tests if batch_type == "distributed"),
        "requires_multi_gpu": batch_type == "distributed",
        "gpu_per_test": gpu_per_test,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=1))

    rp = Path(run_dir) / "batches" / super_id / "batch_results.json"
    rp.unlink(missing_ok=True)
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [sys.executable, exe, "--batch-config", str(cfg_path),
             "--workflow-state", wf, "--batch-id", super_id,
             "--timeout", str(wall_timeout)],
            capture_output=True, text=True, timeout=wall_timeout + 2400, env=env,
        )
        elapsed = time.monotonic() - t0
        if rp.exists():
            rd = json.loads(rp.read_text())
            return {"rc": r.returncode, "elapsed": elapsed, "results": rd,
                    "status": "done"}
        return {"rc": r.returncode, "elapsed": elapsed, "results": None,
                "status": "no_result", "stderr_tail": r.stderr[-300:]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "elapsed": time.monotonic() - t0,
                "results": None}
    except Exception as e:
        return {"status": "error", "error": str(e), "results": None}


def split_back(results: dict, test_to_batch: dict, run_dir: str) -> list:
    """把合并结果按 test id 拆回各原 batch, 写回 batch_results.json + 回写 test_load.

    Returns: 每条原 batch 的摘要 dict 列表.
    """
    wf = str(Path(run_dir) / "workflow_state.json")
    by_batch = defaultdict(list)
    for t in results.get("tests", []):
        bid = test_to_batch.get(t.get("id"))
        if bid:
            by_batch[bid].append(t)

    out = []
    for bid, tests in by_batch.items():
        bdir = Path(run_dir) / "batches" / bid
        bdir.mkdir(exist_ok=True)
        # 按原 batch 重建 batch_results.json (statistics 按当前子集重算)
        stats = Counter(t.get("status") for t in tests)
        br = {
            "batch_id": bid,
            "started_at": results.get("started_at"),
            "finished_at": results.get("finished_at"),
            "timeout": results.get("timeout"),
            "exit_code": results.get("exit_code"),
            "remote_log": results.get("remote_log"),
            "tests": tests,
            "statistics": {
                "total": len(tests),
                "passed": stats.get("passed", 0),
                "failed": stats.get("failed", 0),
                "error": stats.get("error", 0),
                "skipped": stats.get("skipped", 0),
                "retriable_error": stats.get("retriable_error", 0),
                "ignored": stats.get("ignored", 0),
            },
        }
        rp = bdir / "batch_results.json"
        rp.write_text(json.dumps(br, ensure_ascii=False, indent=1))
        # 回写 test_load (Bug 3)
        ur = subprocess.run(
            [sys.executable,
             str(PROJECT_ROOT / "skills/ut/ut_common/update_test_load_two_phase.py"),
             "--batch-id", bid, "--batch-results", str(rp),
             "--workflow-state", wf],
            capture_output=True, text=True)
        if ur.returncode != 0:
            print(f"  [WARN] test_load update failed for {bid}: {ur.stderr.strip()[:200]}")
        st = br["statistics"]
        out.append({
            "batch_id": bid, "status": "done",
            "passed": st["passed"], "failed": st["failed"],
            "error": st["error"], "ignored": st["ignored"],
            "tests": len(tests),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=str(RUN_DIR))
    ap.add_argument("--max-batch-size", type=int, default=8,
                    help="合并 batch 的测试数上限 (默认 8, 单 execute_batch 内部并行)")
    ap.add_argument("--limit", type=int, default=None, help="只重跑前 N 个 batch (试点)")
    ap.add_argument("--timeout", type=int, default=600, help="每测试 watchdog 超时秒数 (默认 600)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    report = json.loads((run_dir / "phase2_stage1_report.json").read_text())
    batches = report["error_statistics"]["timeout"]["batch_list"]
    if args.limit:
        batches = batches[:args.limit]

    # ── 收集所有 timeout batch 的 tests, 记录原 batch 归属 ──────────────
    test_to_batch = {}   # test_id -> 原 batch_id
    # 按 batch_type 分组收集: distributed (gpu_per_test=2) 与 normal 必须分开
    # 合并, 混在一起 execute_batch 会按错误的 gpu_per_test 分配 GPU。
    grouped = defaultdict(list)  # batch_type -> [(test, batch_id)]
    skipped_batches = 0
    for bid in batches:
        cfg_path = run_dir / "batches" / bid / "batch_config.json"
        if not cfg_path.exists():
            skipped_batches += 1
            continue
        cfg = json.loads(cfg_path.read_text())
        btype = cfg.get("batch_type", "normal")
        for t in cfg.get("tests", []):
            if t.get("id") in test_to_batch:
                continue  # 同一测试出现在多个 batch 只取第一个
            test_to_batch[t["id"]] = bid
            grouped[btype].append((t, bid))
    total_tests = sum(len(v) for v in grouped.values())
    print(f"[retry] 收集 {total_tests} 个测试来自 {len(batches)} 个 timeout batch "
          f"(跳过 config 缺失 {skipped_batches}), max-batch-size={args.max_batch_size}")
    for btype, items in grouped.items():
        print(f"  - {btype}: {len(items)} 个测试")

    # ── 切成 super-batches (每个 batch_type 独立切分) ─────────────────────
    super_batches = []   # (batch_type, tests, 原 batch ids)
    for btype, items in grouped.items():
        cur_tests, cur_bids = [], set()
        for t, bid in items:
            if len(cur_tests) >= args.max_batch_size:
                super_batches.append((btype, cur_tests, sorted(cur_bids)))
                cur_tests, cur_bids = [], set()
            cur_tests.append(t)
            cur_bids.add(bid)
        if cur_tests:
            super_batches.append((btype, cur_tests, sorted(cur_bids)))
    print(f"[retry] 切成 {len(super_batches)} 个 super-batch")

    # ── 单进程串行跑每个 super-batch (execute_batch 内部并行) ─────────────
    results = []
    t_start = time.monotonic()
    for i, (btype, stests, sbids) in enumerate(super_batches, 1):
        gpu_per_test = 2 if btype == "distributed" else 1
        super_id = f"super_{i:04d}"
        print(f"  [{i}/{len(super_batches)}] {super_id}: {len(stests)} 测试 "
              f"({len(sbids)} 个原 batch) {btype} gpu_per_test={gpu_per_test}",
              flush=True)
        r = run_super_batch(super_id, stests, str(run_dir), args.timeout,
                            btype, gpu_per_test)
        if r.get("status") != "done" or not r.get("results"):
            print(f"    → {r.get('status')} rc={r.get('rc')} {r.get('elapsed',0):.0f}s"
                  f" {r.get('stderr_tail','')}")
            # 拆不回结果, 记录原 batch 为 no_result
            for bid in sbids:
                results.append({"batch_id": bid, "status": "no_result",
                                "error": r.get("error", r.get("status"))})
            continue
        # 拆回 + 回写
        per_batch = split_back(r["results"], test_to_batch, str(run_dir))
        results.extend(per_batch)
        done_p = sum(x.get("passed", 0) for x in per_batch)
        done_f = sum(x.get("failed", 0) for x in per_batch)
        print(f"    → done {r['elapsed']:.0f}s: p={done_p} f={done_f} "
              f"({len(per_batch)} 个原 batch 回写)", flush=True)
        # 增量保存
        (run_dir / "retry_timeout_progress.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1))

    total = time.monotonic() - t_start
    summary = {
        "total": len(batches),
        "super_batches": len(super_batches),
        "elapsed_secs": total,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = run_dir / "retry_timeout_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n[retry] 完成 {len(batches)} batches ({len(super_batches)} super-batches) "
          f"in {total:.0f}s → {out}")
    statuses = Counter(r.get("status") for r in results)
    print(f"状态分布: {dict(statuses)}")
    passed_tests = sum(r.get("passed", 0) for r in results)
    failed_tests = sum(r.get("failed", 0) for r in results)
    print(f"重跑后: passed={passed_tests}, failed={failed_tests}")


if __name__ == "__main__":
    main()
