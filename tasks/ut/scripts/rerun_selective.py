#!/usr/bin/env python3
"""rerun_selective.py — 通用选择性重跑器 (batch/ssh 双执行模式).

2026-08-18 整合自 tasks/ut/scripts 下 5 个同构重跑脚本:
  rerun_flaky / rerun_marlin / run_remaining_80 / rerun_ignored_remaining /
  retry_kernel_tests。能力:
  1. 从 run 目录自动定位最新 test_load_*.json
  2. 按 status/category/match-node/match-error/limit 过滤目标
  3. batch 模式: 分组 → 写 batch_config → execute_batch (bifrost) → 回写
     (已存在的 batch 目录自动跳过 = 断点续跑)
  4. ssh 模式: SSH docker exec 单跑 pytest → 解析 → 直接回写
     (progress 文件断点续跑)
  5. device-map 替换/还原 (如 cuda:1=cuda:0, 回写用原 node)

用法示例:
  # 重跑 ignored (默认排除兼容性 SKIP 类, 与旧 rerun_ignored_remaining 等价)
  python3 rerun_selective.py --run-dir runs/ut-20260807-110322 --status ignored
  # 重跑 flaky (旧 rerun_flaky)
  python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status failed \
      --match-error ProcessRaisedException
  # 重跑 marlin 算子类 (旧 rerun_marlin)
  python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status failed \
      --match-error moe_wna16_marlin_gemm
  # 补跑前 80 条 pending (旧 run_remaining_80)
  python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status pending --limit 80
  # kernel 串行 SSH 直跑 (旧 retry_kernel_tests, 断点续跑自动)
  python3 rerun_selective.py --run-dir runs/ut-20260718-164107 --status ignored \
      --match-node tests/kernels/attention/ --executor ssh --tag kernel
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXEC = PROJECT_ROOT / "skills/ut/unit-test-executor/scripts/execute_batch.py"
UPD = PROJECT_ROOT / "skills/ut/ut_common/update_test_load_two_phase.py"

DEFAULT_BIFROST_CONFIG = "/gpfs/gcsp/liuxin/bifrost_test/settings.json"
DEFAULT_HF_HOME = "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"
DEFAULT_SSH_HOST = "infra-gpu-h20-022.host.shzhisuan.com"
DEFAULT_SSH_CONTAINER = "v0.13.0_torch2.5.1_compile"
DEFAULT_VLLM_DIR = "/gpfs/gcsp/M2.7_verify/vllm"

# 默认跳过的文件 (HF 下载卡死 / stale 节点, 2026-08-08 根因)
SKIP_FILES = ("test_detokenize", "test_peft_helper")

# 兼容性 SKIP 类 (记录根因不重跑 — 2026-08-09 用户拍板)
SKIP_CATEGORIES = ("_C算子", "FP8", "inductor", "flash/mla", "cutlass", "torch API")


# ---------- 纯函数 (可测) ----------

def _classify(t):
    """按 error_message/test_file 分类 (兼容性 SKIP vs 可重跑组)."""
    e = (t.get("error_message") or t.get("error_type") or "")[:200]
    f = (t.get("test_file") or t.get("test_node") or "").split("/")[-1]
    if any(k in f for k in ("marlin", "gptq", "awq", "gguf")) or "NotImplementedError" in e:
        return "_C算子"
    if "fp8" in f or "float8" in f:
        return "FP8"
    if any(k in f for k in ("fusion", "inductor", "compile", "dynamo")) or "BackendCompilerFailed" in e:
        return "inductor"
    if any(k in f for k in ("flash_attn", "flashmla", "mla_backend", "attention_backend")):
        return "flash/mla"
    if any(k in f for k in ("cutlass", "machete")):
        return "cutlass"
    if "module 'torch' has no attribute" in e:
        return "torch API"
    if "JUnit XML" in e or "watchdog SIGKILL" in e:
        return "timeout"
    if any(k in e for k in ("LocalEntryNotFound", "404", "OfflineMode", "connection", "HF_")):
        return "models"
    if "skipped" in e.lower() or "SKIPPED" in e:
        return "skipped"
    return "other"


def select_targets(tests, *, status="ignored", category="all",
                   match_node=(), match_error=(), skip_files=SKIP_FILES,
                   no_skip=False, only_retry_zero=False, limit=None):
    """过滤 test_load tests → 重跑目标.

    category: all=排除兼容性 SKIP 类; 指定组=只选该组.
    match_node/match_error: 子串过滤 (test_node / error_message), 可多个.
    only_retry_zero: 只选 retry_count==0 (ssh 模式 kernel 场景).
    """
    targets = []
    for t in tests:
        if t.get("status") != status:
            continue
        node = t.get("test_node") or ""
        if match_node and not all(m in node for m in match_node):
            continue
        if match_error:
            e = t.get("error_message") or t.get("error_type") or ""
            if not all(m in e for m in match_error):
                continue
        if only_retry_zero and int(t.get("retry_count", 0)) != 0:
            continue
        if not no_skip and any(f in node for f in skip_files):
            continue
        if category != "all":
            if _classify(t) != category:
                continue
        elif _classify(t) in SKIP_CATEGORIES:
            continue
        targets.append(t)
    if limit is not None:
        targets = targets[:limit]
    return targets


def make_groups(targets, batch_size):
    """均匀分组 (batch 模式用)."""
    return [targets[i:i + batch_size] for i in range(0, len(targets), batch_size)]


def apply_device_map(node, dev_map):
    """运行层替换: cuda:1 → cuda:0."""
    for src, dst in dev_map.items():
        node = node.replace(src, dst)
    return node


def restore_device_map(node, dev_map):
    """回写还原: cuda:0 → 原 cuda:1."""
    for dst, src in [(v, k) for k, v in dev_map.items()]:
        node = node.replace(dst, src)
    return node


def build_batch_config(bid, tests, generated_at=None):
    return {
        "batch_id": bid, "batch_type": "normal", "tests": tests,
        "distributed_count": 0, "requires_multi_gpu": False,
        "gpu_per_test": 1,
        "generated_at": generated_at or datetime.now().isoformat(),
    }


def parse_pytest_output(out: str, elapsed: float):
    """解析 pytest 结果行 (ssh 模式), 返回结果 dict.

    如 \"1 passed, 3 warnings in 2.19s\" / \"1 failed, 1 error in 2.40s\" /
    \"2 skipped in 1.0s\".
    """
    fm = re.search(r"(\d+) failed", out)
    em = re.search(r"(\d+) error", out)
    pm = re.search(r"(\d+) passed", out)
    sm = re.search(r"(\d+) skipped", out)
    durs = re.search(r"in ([\d.]+)s", out)
    duration_ms = int(float(durs.group(1)) * 1000) if durs else int(elapsed * 1000)

    err_lines = [l.strip() for l in out.splitlines()
                 if l.strip().startswith(("ERROR", "E ", "AssertionError",
                                          "RuntimeError", "FAILED", "INTERNALERROR"))]
    err_msg = "\n".join(err_lines[:5])[:500] if err_lines else ""

    n_failed = int(fm.group(1)) if fm else 0
    n_error = int(em.group(1)) if em else 0
    n_passed = int(pm.group(1)) if pm else 0
    n_skipped = int(sm.group(1)) if sm else 0

    if n_error > 0:
        return {"status": "error", "error_type": "error",
                "error_message": err_msg, "duration_ms": duration_ms}
    if n_failed > 0:
        return {"status": "failed", "error_type": "assertion",
                "error_message": err_msg, "duration_ms": duration_ms}
    if n_passed > 0:
        return {"status": "passed", "error_type": None,
                "error_message": "", "duration_ms": duration_ms}
    if n_skipped > 0:
        return {"status": "ignored", "error_type": "filtered",
                "error_message": "skipped", "duration_ms": duration_ms}
    # 没解析到结果行: 可能 not found 或其他
    if "not found" in out or "no tests ran" in out or "no tests collected" in out:
        return {"status": "ignored", "error_type": "timeout",
                "error_message": "pytest not found/no tests: " + out[-200:],
                "duration_ms": duration_ms}
    return {"status": "ignored", "error_type": "other",
            "error_message": "unparsed: " + out[-300:], "duration_ms": duration_ms}


def load_test_load(run_dir):
    """定位 run 目录下最新 test_load_*.json, 返回 (path, tests)."""
    tls = sorted(run_dir.glob("test_load_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    if not tls:
        raise FileNotFoundError(f"{run_dir} 下无 test_load_*.json")
    tl = json.loads(tls[0].read_text(encoding="utf-8"))
    return tls[0], tl.get("tests", [])


def build_env(bifrost_config, hf_home):
    """execute_batch 进程 env (bifrost 后端 + HF 离线兜底, 2026-08-08 根因)."""
    return {
        "REMOTE_BACKEND": "bifrost",
        "BIFROST_CONFIG": bifrost_config,
        "HF_HOME": hf_home,
        "HF_HUB_OFFLINE": "1",
    }


# ---------- ssh 模式 ----------

def run_ssh_one(host, container, vllm_dir, node, timeout=180):
    """SSH H20 docker exec 单跑一个节点 (不设 CUDA_VISIBLE_DEVICES), 返回结果 dict."""
    ssh_cmd = (
        f"timeout {timeout} ssh -o BatchMode=yes -o ConnectTimeout=8 {host} "
        f'"sudo -n docker exec {container} bash -lc \'cd {vllm_dir} && '
        f"python3 -m pytest \\\"{node}\\\" -q --no-header --tb=line "
        f"2>&1 | tail -40'\\\""
    )
    t0 = time.monotonic()
    try:
        r = subprocess.run(ssh_cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout + 20)
        out = (r.stdout or "") + (r.stderr or "")
        elapsed = time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return {"status": "ignored", "error_type": "timeout",
                "error_message": "ssh timeout", "duration_ms": None}
    except Exception as e:
        return {"status": "ignored", "error_type": "other",
                "error_message": f"ssh failed: {e}", "duration_ms": None}
    return parse_pytest_output(out, elapsed)


def write_back_direct(run_dir, results):
    """按 test_node 回写 test_load (ssh 模式直写, 不经过 update_test_load_two_phase)."""
    tls = sorted(run_dir.glob("test_load_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    path = tls[0]
    tl = json.loads(path.read_text(encoding="utf-8"))
    by_node = {t.get("test_node"): t for t in tl["tests"]}
    updated = 0
    for node, res in results.items():
        t = by_node.get(node)
        if not t:
            continue
        t["status"] = res["status"]
        t["error_type"] = res.get("error_type")
        t["error_message"] = res.get("error_message")
        t["duration_ms"] = res.get("duration_ms")
        t["last_run_at"] = datetime.now().isoformat()
        t["run_count"] = int(t.get("run_count", 0)) + 1
        if res["status"] in ("failed", "error"):
            t["retry_count"] = int(t.get("retry_count", 0)) + 1
        updated += 1
    path.write_text(json.dumps(tl, indent=2, ensure_ascii=False))
    print(f"[write_back] 更新 {updated} 条 → {path.name}")


# ---------- 执行模式 ----------

def run_batch_mode(run_dir, targets, *, prefix, batch_size, batch_timeout,
                   device_map, env, resume=True):
    """batch 模式: 分组 → batch_config → execute_batch → update_test_load_two_phase 回写."""
    groups = make_groups(targets, batch_size)
    print(f"[rerun] {len(groups)} 批 ({batch_size}/批, 顺序执行)")
    t0 = time.time()
    ws_path = run_dir / "workflow_state.json"
    for gi, tests in enumerate(groups, 1):
        bid = f"batch_{prefix}_{gi:04d}"
        cfg_dir = run_dir / "batches" / bid
        if resume and (cfg_dir / "batch_results.json").exists():
            print(f"  · {bid}: 已有结果, 跳过 (断点续跑)")
            continue
        cfg_dir.mkdir(parents=True, exist_ok=True)
        run_tests = []
        for t in tests:
            tt = dict(t)
            tt["test_node"] = apply_device_map(tt.get("test_node", ""), device_map)
            run_tests.append(tt)
        cfg = build_batch_config(bid, run_tests)
        (cfg_dir / "batch_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=1))
        try:
            r = subprocess.run(
                [sys.executable, str(EXEC), "--batch-config", str(cfg_dir / "batch_config.json"),
                 "--workflow-state", str(ws_path), "--batch-id", bid,
                 "--timeout", str(batch_timeout)],
                capture_output=True, text=True, env={**os.environ, **env}, timeout=3600)
        except subprocess.TimeoutExpired:
            print(f"  ✗ {bid}: execute_batch 3600s 超时 (跳过, 残留需清理)")
            continue
        brp = cfg_dir / "batch_results.json"
        if r.returncode != 0 or not brp.exists():
            print(f"  ✗ {bid}: rc={r.returncode} (继续下一批)")
            continue
        # device-map 回写还原: results 的 node 还原为原 node
        if device_map:
            br = json.loads(brp.read_text(encoding="utf-8"))
            for t in br.get("tests", []):
                t["test_node"] = restore_device_map(t.get("test_node", ""), device_map)
            brp.write_text(json.dumps(br, ensure_ascii=False, indent=1))
        subprocess.run(
            [sys.executable, str(UPD), "--workflow-state", str(ws_path),
             "--batch-id", bid, "--batch-results", str(brp)],
            capture_output=True, text=True, env={**os.environ, **env}, timeout=300)
        br = json.loads(brp.read_text(encoding="utf-8"))
        st = br.get("statistics", {})
        if gi % 25 == 0 or gi == len(groups):
            el = time.time() - t0
            tl2 = json.loads(load_test_load(run_dir)[0].read_text(encoding="utf-8"))
            c = Counter(t["status"] for t in tl2["tests"])
            print(f"  [{gi}/{len(groups)}] {el/60:.0f}min | test_load p={c.get('passed')} "
                  f"ig={c.get('ignored')} | 本批 p={st.get('passed')}")
    tl_path, _ = load_test_load(run_dir)
    c = Counter(t["status"] for t in json.loads(tl_path.read_text(encoding="utf-8"))["tests"])
    print(f"[rerun] 完成 {len(groups)} 批 | {(time.time()-t0)/60:.0f}min | test_load: {dict(c)}")


def run_ssh_mode(run_dir, targets, *, host, container, vllm_dir, tag,
                 device_map, ssh_timeout, limit=None):
    """ssh 模式: SSH docker exec 单跑 + progress 断点续跑 + 直接回写."""
    # 断点续跑: 跳过 progress 里已有的节点 (中断后重启不重跑)
    progress_path = run_dir / f"retry_{tag}_progress.json"
    existing = {}
    if progress_path.exists():
        try:
            existing = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if existing:
        before = len(targets)
        targets = [t for t in targets if t["test_node"] not in existing]
        print(f"[ssh] 断点续跑: 跳过已有 {before - len(targets)} 个, 剩余 {len(targets)} 个")
    if limit is not None:
        targets = targets[:limit]
    print(f"[ssh] 收集 {len(targets)} 个目标 (host={host})")

    results = dict(existing)
    t_start = time.monotonic()
    done = 0
    passed = failed = error = ignored = 0
    for t in targets:
        node = t["test_node"]
        run_node = apply_device_map(node, device_map)
        done += 1
        res = run_ssh_one(host, container, vllm_dir, run_node, timeout=ssh_timeout)
        results[node] = res
        if res["status"] == "passed":
            passed += 1
        elif res["status"] == "failed":
            failed += 1
        elif res["status"] == "error":
            error += 1
        else:
            ignored += 1
        print(f"  [{done}/{len(targets)}] {res['status']:8s} "
              f"{(res.get('duration_ms') or 0)/1000:.1f}s {node[:70]}")
        if done % 20 == 0:
            progress_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
            print(f"    → 累计 p={passed} f={failed} e={error} ig={ignored} "
                  f"{(time.monotonic()-t_start)/60:.0f}min")

    progress_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    write_back_direct(run_dir, results)
    total_s = time.monotonic() - t_start
    summary = {
        "total": len(targets), "passed": passed, "failed": failed,
        "error": error, "ignored": ignored,
        "elapsed_secs": total_s, "tag": tag,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / f"retry_{tag}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n[ssh] 完成 {len(targets)} 个 in {total_s/60:.0f}min: "
          f"passed={passed} failed={failed} error={error} ignored={ignored}")


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True, help="run 目录 (必选, 含 test_load_*.json)")
    ap.add_argument("--status", default="ignored",
                    help="要重跑的状态 (ignored/failed/pending/error, 默认 ignored)")
    ap.add_argument("--category", default="all",
                    help="按失败类别过滤: all/skipped/models/other/timeout/... (默认 all=排除兼容性 SKIP 类)")
    ap.add_argument("--match-node", action="append", default=[],
                    help="只选 test_node 含该子串的用例 (可多次, 全含才选)")
    ap.add_argument("--match-error", action="append", default=[],
                    help="只选 error_message 含该子串的用例 (可多次, 全含才选)")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个")
    ap.add_argument("--max-batch-size", type=int, default=8, help="每批测试数 (默认 8)")
    ap.add_argument("--prefix", default="ig", help="batch 前缀 (避免多进程命名冲突, 默认 ig)")
    ap.add_argument("--no-skip", action="store_true", help="不跳过 SKIP_FILES (全量跑)")
    ap.add_argument("--skip-files", default=",".join(SKIP_FILES),
                    help="跳过的文件子串 (逗号分隔, 默认 test_detokenize,test_peft_helper)")
    ap.add_argument("--device-map", default=None, help="运行层 device 替换, 如 cuda:1=cuda:0")
    ap.add_argument("--batch-timeout", type=int, default=900, help="每用例超时秒数 (默认 900)")
    ap.add_argument("--executor", choices=["batch", "ssh"], default="batch",
                    help="执行模式: batch=execute_batch 批跑 (默认); ssh=SSH 单跑 pytest")
    ap.add_argument("--only-retry-zero", action="store_true",
                    help="只选 retry_count==0 (ssh 模式 kernel 场景)")
    ap.add_argument("--tag", default="kernel", help="ssh 模式 progress/汇总文件标签 (默认 kernel)")
    ap.add_argument("--ssh-host", default=DEFAULT_SSH_HOST)
    ap.add_argument("--ssh-container", default=DEFAULT_SSH_CONTAINER)
    ap.add_argument("--ssh-vllm-dir", default=DEFAULT_VLLM_DIR)
    ap.add_argument("--ssh-timeout", type=int, default=180, help="单用例 SSH 超时秒数 (默认 180)")
    ap.add_argument("--bifrost-config", default=DEFAULT_BIFROST_CONFIG)
    ap.add_argument("--hf-home", default=DEFAULT_HF_HOME)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = PROJECT_ROOT / run_dir
    if not run_dir.is_dir():
        ap.error(f"run 目录不存在: {run_dir}")

    tl_path, tests = load_test_load(run_dir)
    skip = () if args.no_skip else tuple(s.strip() for s in args.skip_files.split(",") if s.strip())
    targets = select_targets(
        tests, status=args.status, category=args.category,
        match_node=tuple(args.match_node), match_error=tuple(args.match_error),
        skip_files=skip, only_retry_zero=args.only_retry_zero, limit=args.limit)
    print(f"[rerun] {tl_path.name}: {len(tests)} 条, 目标 {len(targets)} 个 "
          f"(status={args.status}, category={args.category})")

    dev_map = {}
    if args.device_map and "=" in args.device_map:
        src, dst = args.device_map.split("=", 1)
        dev_map[src] = dst
        print(f"[rerun] device-map: {src} → {dst} (回写用原 node)")
    if not targets:
        print("无目标")
        return

    env = build_env(args.bifrost_config, args.hf_home)
    if args.executor == "ssh":
        run_ssh_mode(run_dir, targets, host=args.ssh_host, container=args.ssh_container,
                     vllm_dir=args.ssh_vllm_dir, tag=args.tag, device_map=dev_map,
                     ssh_timeout=args.ssh_timeout)
    else:
        run_batch_mode(run_dir, targets, prefix=args.prefix,
                       batch_size=args.max_batch_size, batch_timeout=args.batch_timeout,
                       device_map=dev_map, env=env)


if __name__ == "__main__":
    main()
