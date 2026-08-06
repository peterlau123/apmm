#!/usr/bin/env python3
"""串行重跑可救的 kernel 测试 (test_cache + prefix_prefill), 2026-08-05.

背景: execute_batch 设 CUDA_VISIBLE_DEVICES=单卡 → vllm kernel 测试参数化
(cuda:1-...) 节点 not found → pytest 收集 0 → ignored。单独跑 (不设 env)
全部 passed (2.2-2.9s/个)。fused_quant_layernorm 403 个 illegal memory
access 真崩, 不在此列 (见兼容性报告)。

用法:
  python3 tasks/ut/scripts/retry_kernel_tests.py --run-dir runs/ut-20260718-164107
  [--limit N] [--host infra-gpu-h20-022.host.shzhisuan.com] [--container v0.13.0_torch2.5.1_compile]
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOST = "infra-gpu-h20-022.host.shzhisuan.com"
CONTAINER = "v0.13.0_torch2.5.1_compile"
VLLM_DIR = "/gpfs/gcsp/M2.7_verify/vllm"

# 只跑这两个文件 (fused_quant_layernorm illegal memory access 已排除)
KERNEL_FILES = ("tests/kernels/attention/test_cache.py",
                "tests/kernels/attention/test_prefix_prefill.py")


def collect_targets(run_dir: Path, files: tuple, device: str | None = None):
    """从 test_load 收集目标: ignored 且 retry=0 的指定文件用例 (可加 device 过滤)."""
    tls = sorted(run_dir.glob("test_load_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    tl = json.loads(tls[0].read_text())
    targets = []
    for t in tl.get("tests", []):
        node = t.get("test_node") or ""
        if not any(node.startswith(f) for f in files):
            continue
        if device and device not in node:
            continue
        if t.get("status") == "ignored" and t.get("retry_count", 0) == 0:
            targets.append(t)
    return targets


def run_one(host: str, node: str) -> dict:
    """SSH H20 docker exec 单跑一个节点 (不设 CUDA_VISIBLE_DEVICES), 返回结果 dict."""
    ssh_cmd = (
        f"timeout 180 ssh -o BatchMode=yes -o ConnectTimeout=8 {host} "
        f'"sudo -n docker exec {CONTAINER} bash -lc \'cd {VLLM_DIR} && '
        f"python3 -m pytest \\\"{node}\\\" -q --no-header --tb=line "
        f"2>&1 | tail -40'\""
    )
    t0 = time.monotonic()
    try:
        r = subprocess.run(ssh_cmd, shell=True, capture_output=True,
                           text=True, timeout=200)
        out = (r.stdout or "") + (r.stderr or "")
        elapsed = time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return {"status": "ignored", "error_type": "timeout",
                "error_message": "ssh timeout", "duration_ms": None}
    except Exception as e:
        return {"status": "ignored", "error_type": "other",
                "error_message": f"ssh failed: {e}", "duration_ms": None}

    # 解析 pytest 结果行, 如 "1 passed, 3 warnings in 2.19s" /
    # "1 failed, 1 error in 2.40s" / "2 skipped in 1.0s" (warnings 忽略)
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


def write_back(run_dir: Path, results: dict):
    """按 test_node 回写 test_load (status/error_type/error_message/retry_count)."""
    tls = sorted(run_dir.glob("test_load_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    path = tls[0]
    tl = json.loads(path.read_text())
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=str(PROJECT_ROOT / "runs" / "ut-20260718-164107"))
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个 (试点)")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--file", default=",".join(KERNEL_FILES),
                    help="要跑的文件前缀 (逗号分隔)")
    ap.add_argument("--device", default=None,
                    help="只跑 node 含该字符串的用例 (如 cuda:0, 避开异常卡)")
    ap.add_argument("--device-map", default=None,
                    help="运行层替换 device, 如 cuda:1=cuda:0 (回写用原 node)")
    ap.add_argument("--tag", default="kernel",
                    help="进度/汇总文件名标签, 如 fql")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    files = tuple(f.strip() for f in args.file.split(",") if f.strip())

    targets = collect_targets(run_dir, files, args.device)
    # 断点续跑: 跳过 progress 里已有的节点 (中断后重启不重跑)
    progress_path = run_dir / f"retry_{args.tag}_progress.json"
    existing = set()
    if progress_path.exists():
        try:
            existing = set(json.loads(progress_path.read_text()).keys())
        except Exception:
            pass
    if existing:
        before = len(targets)
        targets = [t for t in targets if t["test_node"] not in existing]
        print(f"[kernel] 断点续跑: 跳过已有 {before - len(targets)} 个, 剩余 {len(targets)} 个")
    if args.limit:
        targets = targets[:args.limit]
    print(f"[kernel] 收集 {len(targets)} 个目标 (files={files}, device={args.device}, "
          f"ignored retry=0)")

    # device-map: cuda:1=cuda:0 → 运行时替换 node 里的 device, 回写用原 node
    dev_map = {}
    if args.device_map and "=" in args.device_map:
        src, dst = args.device_map.split("=", 1)
        dev_map[src] = dst
        print(f"[kernel] device-map: {src} → {dst}")

    # 载入已有结果保持计数准确 (断点续跑)
    results = {}
    if existing:
        try:
            results = {k: v for k, v in json.loads(progress_path.read_text()).items()}
        except Exception:
            pass
    t_start = time.monotonic()
    done = 0
    passed = failed = error = ignored = 0
    for t in targets:
        node = t["test_node"]
        run_node = node
        for src, dst in dev_map.items():
            run_node = run_node.replace(src, dst)
        done += 1
        res = run_one(args.host, run_node)
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
    write_back(run_dir, results)
    total_s = time.monotonic() - t_start
    summary = {
        "total": len(targets), "passed": passed, "failed": failed,
        "error": error, "ignored": ignored,
        "elapsed_secs": total_s,
        "files": list(files), "device": args.device,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / f"retry_{args.tag}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n[kernel] 完成 {len(targets)} 个 in {total_s/60:.0f}min: "
          f"passed={passed} failed={failed} error={error} ignored={ignored}")


if __name__ == "__main__":
    main()
