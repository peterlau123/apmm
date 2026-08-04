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
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RUN_DIR = PROJECT_ROOT / "runs" / "ut-20260718-164107"
# 自动重试参数 (2026-08-04): ignored/no_result 不视为完成, 最多重试次数与等待
MAX_RETRIES = 3
RETRY_WAIT = 30  # 秒, 避开环境冲突窗口 (并发/flashinfer 竞争)
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

    # super-batch 的 config 写到 batches/{super_id}/ (与正常 batch 同结构)。
    # 注意: execute_batch 把 batch_results.json 写到 batch-config 同目录
    # (batch_dir = config 的父目录), 放 .superbatches/ 会导致结果写在
    # .superbatches/batch_results.json 而 retry 检查 batches/... 找不到
    # → no_result。实测踩坑 2026-08-04。
    bdir = Path(run_dir) / "batches" / super_id
    bdir.mkdir(parents=True, exist_ok=True)
    cfg_path = bdir / "batch_config.json"
    cfg_path.write_text(json.dumps({
        "batch_id": super_id,
        "batch_type": batch_type,
        "tests": tests,
        "distributed_count": sum(1 for t in tests if batch_type == "distributed"),
        "requires_multi_gpu": batch_type == "distributed",
        "gpu_per_test": gpu_per_test,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=1))

    rp = bdir / "batch_results.json"
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
        # DEBUG 2026-08-04: 打印 execute_batch 完整输出 (定位探测 0 卡问题)
        if True:
            print(f"    [DBG] rc={r.returncode} stdout tail: "
                  f"{(r.stdout or '')[-800:]}", flush=True)
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
        # 同一原 batch 可能被拆到多个 super-batch (8 测试 2 卡分两轮),
        # batch_results.json 已有旧结果时 MERGE (按 test id 去重), 不覆盖。
        prev = {}
        prev_path = bdir / "batch_results.json"
        if prev_path.exists():
            try:
                prev = {t["id"]: t for t in json.loads(prev_path.read_text()).get("tests", [])}
            except Exception:
                prev = {}
        merged_tests = {t["id"]: t for t in tests}
        merged_tests.update({k: v for k, v in prev.items() if k not in merged_tests})
        merged_list = list(merged_tests.values())
        # 按原 batch 重建 batch_results.json (statistics 按当前子集重算)
        stats = Counter(t.get("status") for t in merged_list)
        br = {
            "batch_id": bid,
            "started_at": results.get("started_at"),
            "finished_at": results.get("finished_at"),
            "timeout": results.get("timeout"),
            "exit_code": results.get("exit_code"),
            "remote_log": results.get("remote_log"),
            "tests": merged_list,
            "statistics": {
                "total": len(merged_list),
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
            "tests": len(merged_list),
        })
    return out


def load_slow_tests(run_dir: Path, ut_logs_base=None,
                    slow_threshold: float = 600) -> tuple:
    """找出已知慢测试 (重试超限 + XML 实测超时), 重试时跳过避免连坐。

    两个来源:
    1. test_load: status=ignored 且 retry_count>=3 (重试已超限, 8/4 实测
       retry 5-11 次仍 ignored) —— key 是 test_id (数字) 和 test_node
    2. ut_logs 的 result_*.xml: testcase time > slow_threshold (Phase 1
       XML 实测, 如 test_sequence_parallelism 19-20min —— 这些 retry=0
       没被来源 1 覆盖, 但放回队列会再次拖到 watchdog 600s 连坐同批)

    Returns: (slow: {test_id_or_node: reason}, xml_prefixes: [test_node 前缀])
    清单落盘 retry_slow_tests.json 供后续单独处理 (提 timeout 单跑或接受 failed)。
    """
    tls = sorted(run_dir.glob("test_load_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    slow = {}
    if tls:
        tl = json.loads(tls[0].read_text())
        for t in tl.get("tests", []):
            if t.get("status") == "ignored" and t.get("retry_count", 0) >= 3:
                reason = (t.get("ignored_reason")
                          or t.get("error_type") or "slow")
                if t.get("test_id") is not None:
                    slow[str(t["test_id"])] = reason
                if t.get("test_node"):
                    slow[t["test_node"]] = reason
    else:
        print("  [WARN] 无 test_load 文件, 慢测试剔除来源 1 失效", flush=True)

    # 来源 2: XML 实测耗时 > slow_threshold 的测试 (按 test_node 前缀匹配)
    xml_prefixes = []
    if ut_logs_base and ut_logs_base.exists():
        for bdir in ut_logs_base.glob("batch_*/"):
            for f in bdir.glob("result_*.xml"):
                try:
                    tree = ET.parse(f)
                except Exception:
                    continue
                for tc in tree.getroot().iter("testcase"):
                    try:
                        dur = float(tc.get("time", 0))
                    except (TypeError, ValueError):
                        continue
                    if dur > slow_threshold:
                        cls = (tc.get("classname") or "").replace(".", "/") + ".py"
                        prefix = f"{cls}::{tc.get('name') or ''}"
                        # 去参数化后缀 [..] 才能 startswith 匹配 test_node
                        prefix = prefix.split("[")[0]
                        if prefix not in xml_prefixes:
                            xml_prefixes.append(prefix)
        print(f"[retry] XML 实测 >{slow_threshold:.0f}s 慢测试前缀 {len(xml_prefixes)} 个",
              flush=True)

    out = run_dir / "retry_slow_tests.json"
    out.write_text(json.dumps({
        "slow": slow,
        "xml_prefixes": xml_prefixes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=1))
    print(f"[retry] 已知慢测试 {len(slow)} 个 + XML 前缀 {len(xml_prefixes)} 个"
          f" → {out.name}")
    return slow, xml_prefixes


def is_slow_test(t: dict, slow: dict, xml_prefixes: list) -> bool:
    """判断测试是否慢测试 (test_id / test_node / XML 前缀三种匹配)."""
    if str(t.get("id")) in slow:
        return True
    tn = t.get("test_node") or ""
    if tn in slow:
        return True
    return any(tn.startswith(p) for p in xml_prefixes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=str(RUN_DIR))
    ap.add_argument("--max-batch-size", type=int, default=8,
                    help="合并 batch 的测试数上限 (默认 8, 单 execute_batch 内部并行)")
    ap.add_argument("--limit", type=int, default=None, help="只重跑前 N 个 batch (试点)")
    ap.add_argument("--timeout", type=int, default=600, help="每测试 watchdog 超时秒数 (默认 600)")
    ap.add_argument("--ut-logs", default="/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
                    help="vLLM ut_logs 目录 (扫描 XML 实测慢测试)")
    ap.add_argument("--slow-threshold", type=float, default=600,
                    help="XML 实测耗时超过此秒数的测试视为慢测试 (默认 600)")
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
    slow, xml_prefixes = load_slow_tests(run_dir,
                                         Path(args.ut_logs),
                                         args.slow_threshold)
    skipped_slow = 0
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
            # 剔除已知慢测试: 重试超限或 XML 实测超时, 再跑只会连坐同批
            if is_slow_test(t, slow, xml_prefixes):
                skipped_slow += 1
                continue
            test_to_batch[t["id"]] = bid
            grouped[btype].append((t, bid))
    total_tests = sum(len(v) for v in grouped.values())
    print(f"[retry] 收集 {total_tests} 个测试来自 {len(batches)} 个 timeout batch "
          f"(跳过 config 缺失 {skipped_batches}, 跳过慢测试 {skipped_slow}), "
          f"max-batch-size={args.max_batch_size}")
    for btype, items in grouped.items():
        print(f"  - {btype}: {len(items)} 个测试")

    # ── 单进程调度器 + 动态 GPU 感知切批 (2026-08-04 v4) ─────────────────
    # 用户方案: 不搞多进程并发 (多进程各自探测 GPU 会争抢同一批空闲卡)。
    # 单进程串行, 每批启动前探测 H20 空闲 GPU, 按空闲卡数决定批大小:
    #   - normal:      min(剩余测试, 空闲卡数)          (1 卡/测试)
    #   - distributed: min(剩余测试, 空闲卡数 // gpu_per_test)  (2 卡/测试)
    # 切批以"原 batch"为最小单位 (整批纳入, 不拆散) —— 否则同一原 batch
    # 的测试散到多个 super-batch, split_back 多次覆盖同一 batch_results.json。
    results_map = {}  # batch_id -> 摘要 (同 batch 多次回写去重)
    t_start = time.monotonic()
    done_count = 0
    # remaining: {btype: [ (batch_id, tests), ... ]} 保持原 batch 完整
    remaining = {}
    for btype, items in grouped.items():
        by_bid = defaultdict(list)
        for t, bid in items:
            by_bid[bid].append(t)
        remaining[btype] = list(by_bid.items())
    while any(remaining.values()):
        # 探测空闲 GPU (bifrost probe_gpus; 失败时按 4 卡保守处理)
        try:
            from tools.remote_executor import probe_gpus
            idle = probe_gpus(backend="bifrost").get("idle", 4)
        except Exception as e:
            print(f"  [WARN] GPU 探测失败 ({e}), 按 4 卡处理", flush=True)
            idle = 4
        if idle <= 0:
            print(f"  [WAIT] 无空闲 GPU, 等 60s...", flush=True)
            time.sleep(60)
            continue

        # 选一类跑: 优先 normal (占多数), 无 normal 才跑 distributed
        if remaining.get("normal"):
            btype = "normal"
            gpu_per_test = 1
            max_tests = idle
        elif remaining.get("distributed"):
            btype = "distributed"
            gpu_per_test = 2
            max_tests = max(1, idle // gpu_per_test)
        else:
            break

        # 整批纳入: 从队列头开始取原 batch, 直到测试数超过 max_tests
        stests, sbids = [], []
        queue = remaining[btype]
        while queue and len(stests) + len(queue[0][1]) <= max_tests:
            bid, tests = queue.pop(0)
            stests.extend(tests)
            sbids.append(bid)
        if not stests and queue:
            # 单个原 batch 超过 max_tests (如 8 测试但只有 2 卡): 拆开
            bid, tests = queue.pop(0)
            stests = tests[:max_tests]
            # 剩余部分放回队列头 (保持原 batch 完整性已不可能, 记录为部分)
            queue.insert(0, (bid, tests[max_tests:]))
            sbids = [bid]

        done_count += 1
        # batch_id 必须匹配 execute_batch schema: ^batch_[A-Za-z0-9_]+$
        # (super_0001 不匹配 → 结果被 rejected 隔离, 实测踩坑 2026-08-04)
        # ⚠️ 编号避开已存在的 batch_super_* 目录 (2026-08-04: 撞上 8/4 遗留
        # batch_super_0001 目录 + ut_logs 旧 XML → execute_batch 行为异常)。
        existing_supers = [int(p.name.split("_")[-1]) for p in
                           (run_dir / "batches").glob("batch_super_*")
                           if p.name.split("_")[-1].isdigit()]
        next_no = max(existing_supers, default=0) + 1
        super_id = f"batch_super_{next_no:04d}"
        print(f"  [{done_count}] {super_id}: {len(stests)} 测试 "
              f"({len(sbids)} 个原 batch) {btype} gpu_per_test={gpu_per_test} "
              f"空闲GPU={idle}", flush=True)
        # 2026-08-04: 等 daemon 空闲再启动 execute_batch —— 否则上一个
        # super-batch 的测试还在 daemon 队列 (active>0), execute_batch 探测
        # 到 0 卡 → D1 degrade → distributed 崩 (insufficient GPUs)。
        # 调度器侧兜底 (execute_batch 内部也有 5×30s 等待, 但连跑时不够)。
        # v2 (19:30): WAIT 超时后跳过该批 (留到下一轮), 不硬跑 —— 硬跑会
        # 在 daemon 队列满时再提交 4-8 任务 → 洪峰 → daemon 卡死 (active=10
        # 恒满, server.log 停更 20 分钟, 实测 19:21 卡死)。
        import json as _json
        _hb_path = Path(ENV["BIFROST_CONFIG"]).parent / "heartbeat.json"
        _waited = False
        active = 0
        for _wait in range(20):  # 最多 10 分钟
            try:
                hb = _json.loads(_hb_path.read_text())
                active = hb.get("active_tasks", 0)
            except Exception:
                active = 0
            if active == 0:
                break
            _waited = True
            print(f"    [WAIT] daemon active={active}, 等 30s 释放 GPU...", flush=True)
            time.sleep(30)
        if _waited and active > 0:
            print(f"    [SKIP] daemon 持续 active={active} (10 分钟未释放), "
                  f"跳过本批留给下轮 (批次 {sbids[:3]})", flush=True)
            # 放回队列: 整批回队头
            queue.insert(0, (sbids[0], stests))
            for bid_ in sbids[1:]:
                queue.insert(1, (bid_, [t for t, _ in grouped[btype]
                                        if t.get("id") in test_to_batch
                                        and test_to_batch[t.get("id")] == bid_]))
            time.sleep(60)
            continue
        r = run_super_batch(super_id, stests, str(run_dir), args.timeout,
                            btype, gpu_per_test)
        # ── 自动重试 (2026-08-04): ignored/no_result 不视为完成 ─────────
        # 实测: pytest 收集 0 (JUnit XML no testcase) 被标 ignored, 但节点
        # 在源码里有效 (collect-only 验证 1 test collected) —— 是执行时
        # 环境冲突 (并发/flashinfer 竞争) 而非节点失效。重试可恢复。
        attempts = 1
        while attempts <= MAX_RETRIES:
            if r.get("status") != "done" or not r.get("results"):
                # no_result: 无结果文件, 重试
                if attempts < MAX_RETRIES:
                    print(f"    → {r.get('status')} rc={r.get('rc')} "
                          f"{r.get('elapsed',0):.0f}s, 重试 {attempts+1}/{MAX_RETRIES}...",
                          flush=True)
                    time.sleep(RETRY_WAIT)
                    r = run_super_batch(super_id, stests, str(run_dir), args.timeout,
                                        btype, gpu_per_test)
                    attempts += 1
                    continue
                print(f"    → {r.get('status')} rc={r.get('rc')} {r.get('elapsed',0):.0f}s"
                      f" {r.get('stderr_tail','')}", flush=True)
                # 拆不回结果, 记录原 batch 为 no_result
                for bid in sbids:
                    results_map[bid] = {"batch_id": bid, "status": "no_result",
                                        "error": r.get("error", r.get("status"))}
                break
            # done 但 ignored 占比高 → 重试 (ignored = pytest 收集 0, 环境问题)
            tests = r["results"].get("tests", [])
            if tests:
                ignored_cnt = sum(1 for t in tests if t.get("status") == "ignored")
                real_cnt = sum(1 for t in tests if t.get("status") in ("passed", "failed"))
                if ignored_cnt > real_cnt and attempts < MAX_RETRIES:
                    print(f"    → done 但 ignored={ignored_cnt} (> real={real_cnt}), "
                          f"重试 {attempts+1}/{MAX_RETRIES}...", flush=True)
                    time.sleep(RETRY_WAIT)
                    r = run_super_batch(super_id, stests, str(run_dir), args.timeout,
                                        btype, gpu_per_test)
                    attempts += 1
                    continue
            # 拆回 + 回写
            per_batch = split_back(r["results"], test_to_batch, str(run_dir))
            # progress 按 batch_id 去重: 同一原 batch 拆多轮时更新而非新增
            for pb in per_batch:
                results_map[pb["batch_id"]] = pb
            done_p = sum(x.get("passed", 0) for x in per_batch)
            done_f = sum(x.get("failed", 0) for x in per_batch)
            print(f"    → done {r['elapsed']:.0f}s: p={done_p} f={done_f} "
                  f"({len(per_batch)} 个原 batch 回写)", flush=True)
            break
        # 增量保存
        (run_dir / "retry_timeout_progress.json").write_text(
            json.dumps(list(results_map.values()), ensure_ascii=False, indent=1))

    total = time.monotonic() - t_start
    results = list(results_map.values())
    summary = {
        "total": len(batches),
        "super_batches": done_count,
        "elapsed_secs": total,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = run_dir / "retry_timeout_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n[retry] 完成 {len(batches)} batches ({done_count} super-batches) "
          f"in {total:.0f}s → {out}")
    statuses = Counter(r.get("status") for r in results)
    print(f"状态分布: {dict(statuses)}")
    passed_tests = sum(r.get("passed", 0) for r in results)
    failed_tests = sum(r.get("failed", 0) for r in results)
    print(f"重跑后: passed={passed_tests}, failed={failed_tests}")


if __name__ == "__main__":
    main()
