#!/usr/bin/env python3
"""
更新测试状态脚本

支持两种模式：
1. 从 workflow_state.json 读取路径（推荐）
2. 从命令行参数直接指定路径

功能：
1. 批量更新测试状态
2. 单个测试状态更新
3. 同时更新 statistics
4. 支持 failed/passed/pending/error/ignored 五种状态

用法：
    # 从 workflow_state.json 读取路径
    python update_status.py --workflow-state PATH --batch --from-file results.json
    
    # 直接指定路径
    python update_status.py --manifest-path PATH --single "tests/xxx.py::test_func" --status passed
    
    # 设置 ignored 状态
    python update_status.py --manifest-path PATH --single "tests/xxx.py::test_func" --status ignored --reason "版本不兼容"

NOTE: PYTHONPATH must be cleared before importing any project modules to avoid
Hermes venv leaking into apmm subprocesses (fake 'jsonschema not installed').
"""

import os
# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

import json
import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 先设置路径（确保 skills 包可被导入）
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.shared import validate_and_write
from skills.ut.shared.bastion_signals import is_disconnect_blob


# ── Type-B fabrication backstop: stat audit on remote log ─────────────────────
#
# Even if batch_results.json passes schema validation locally, a hand-rolled
# (LLM-fabricated) payload can still claim a remote_log.raw_log_path that
# does NOT exist on the remote host, or whose size_bytes lies. The audit
# below independently verifies the log exists and (where size_bytes is
# present and non-null) matches the recorded byte count.
#
# Failure path: we DO NOT mutate manifest.json; we return a structured error
# so the caller can quarantine the batch.

_AGENT_PY = Path(__file__).resolve().parent.parent.parent.parent.parent / "tools" / "agent.py"

# stat -c '%s %Y' output is two non-negative integers separated by whitespace.
# Scan all stdout lines for this shape rather than picking the last one — log
# preambles ([INFO] ..., [WARN] reconnect, ...) emitted by some agent profiles
# can otherwise hide the real result behind log chatter.
_STAT_LINE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")


def _stat_remote_log(profile: str, raw_log_path: str, *, timeout: int = 60):
    """Return (size_bytes, mtime, disconnect_reason) for ``raw_log_path``.

    On a transient bastion outage, ``disconnect_reason`` is a non-empty string
    so the caller can return `next_action=wait` upstream rather than mis-
    classifying the situation as an audit failure.

    On other errors (missing file, parse failure, ...) returns (None, None, "").
    Never raises.
    """
    try:
        r = subprocess.run(
            [sys.executable, str(_AGENT_PY), "-p", profile, "run",
             "--timeout", str(timeout),
             f"stat -c '%s %Y' {raw_log_path} 2>/dev/null || echo MISSING"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout + 30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, None, f"agent.py invocation failed: {e}"

    stdout = r.stdout or ""
    stderr = r.stderr or ""

    # Disconnect heuristic — non-zero rc + any signal token in either stream.
    # Tokens are owned by skills/ut/shared/bastion_signals.py (single source
    # of truth shared with executor's run_remote).
    if r.returncode != 0:
        if is_disconnect_blob(stdout + "\n" + stderr):
            return None, None, f"bastion disconnect: {stderr.strip()[:200]}"
        return None, None, ""

    # MISSING sentinel beats parsing — the inline `|| echo MISSING` triggers
    # only when stat itself failed (file absent / permission denied).
    if "MISSING" in stdout:
        return None, None, ""

    # Scan all lines for a valid `<size> <mtime>` shape. Tolerates log chatter
    # from agent.py before/after the stat output.
    for line in stdout.splitlines():
        m = _STAT_LINE_RE.match(line)
        if m:
            try:
                return int(m.group(1)), int(m.group(2)), ""
            except ValueError:
                continue
    return None, None, ""


def audit_batch_results(batch_results: dict, profile: str) -> tuple[bool, str]:
    """Stat-audit the remote pytest log referenced by ``batch_results``.

    Returns ``(ok, reason)`` where ``ok=False`` means the audit failed and the
    caller MUST NOT consume ``batch_results.tests`` into the manifest.

    Invariants enforced (in order — first matching invariant fails):
      1. ``remote_log.raw_log_path`` is present.
      2. The remote log exists AND is non-empty (`stat -c %s` > 0). This
         single check catches both "file missing" and "fabricated empty
         log" — it does not depend on ``size_bytes`` agreement.
      3. If ``remote_log.size_bytes`` is recorded as a positive integer, it
         equals the real `stat -c %s` size to within ±N bytes (logs can grow
         by trailing newlines / late writes between summary capture and the
         audit; exact equality would be too strict).

    A transient bastion outage during the audit is signalled via a special
    ``reason`` prefix ``bastion_disconnect:`` so the caller can map it to
    ``next_action=wait`` rather than failing the batch.
    """
    remote_log = (batch_results or {}).get("remote_log") or {}
    raw_log_path = remote_log.get("raw_log_path") or ""
    recorded = remote_log.get("size_bytes")
    if not raw_log_path:
        return False, "batch_results.remote_log.raw_log_path missing"

    actual_size, _, disconnect_reason = _stat_remote_log(profile, raw_log_path)
    if disconnect_reason:
        # Surface as a *disconnect* — caller is expected to map this to
        # next_action=wait, not audit_failed.
        return False, f"bastion_disconnect: {disconnect_reason}"
    if actual_size is None:
        return False, (
            f"remote log not found or stat unparseable: {raw_log_path} "
            f"(profile={profile})"
        )
    if actual_size == 0:
        return False, f"remote log exists but is empty: {raw_log_path}"

    # Equality check: only fire when caller actually recorded a positive int.
    # Tolerance handles a benign late append (e.g. a __WATCHDOG__ sentinel
    # written *after* size_bytes was sampled). Anything bigger than that is
    # a true mismatch.
    if isinstance(recorded, int) and recorded > 0:
        if abs(actual_size - recorded) > 4096:
            return False, (
                f"size_bytes mismatch: recorded={recorded} actual={actual_size} "
                f"({raw_log_path})"
            )
    return True, "ok"


def load_workflow_state(workflow_state_path: Path) -> dict:
    """从 workflow_state.json 加载配置"""
    if not workflow_state_path.exists():
        return {"error": f"workflow_state.json not found: {workflow_state_path}"}
    return json.loads(workflow_state_path.read_text(encoding="utf-8"))


def load_manifest(manifest_path: Path) -> dict:
    """加载 manifest.json"""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest 文件不存在: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict, manifest_path: Path) -> tuple[bool, list[str]]:
    """
    保存 manifest.json

    Returns:
        (is_valid, errors): 是否成功写入，错误列表
    """
    # 重新计算 statistics
    manifest["statistics"] = calculate_statistics(manifest["tests"])
    manifest["generated_at"] = datetime.now().isoformat()

    # 校验后写入
    is_valid, errors = validate_and_write(manifest, "manifest", manifest_path)
    if not is_valid:
        return False, errors

    # 同时更新 test_list.txt（如果存在）
    testlist_path = manifest_path.parent / "test_list.txt"
    if testlist_path.parent.exists():
        testlist_path.write_text(
            "\n".join(t["test_node"] for t in manifest["tests"]),
            encoding="utf-8"
        )

    return True, []


def calculate_statistics(tests: list) -> dict:
    """计算统计数据"""
    stats = {
        "pending": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "ignored": 0,
        "total": len(tests),
    }
    
    for test in tests:
        status = test.get("status", "pending")
        if status in stats:
            stats[status] += 1
    
    stats["executed"] = stats["passed"] + stats["failed"] + stats["error"]
    stats["progress"] = round(stats["executed"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
    
    return stats


# v5 merge logic (ported from update_manifest.py) -----------------------------------

def merge_batch_results(manifest: dict, batch_results: dict, handled: dict) -> int:
    """v5 manifest merge ? the canonical update path for Stage 5.

    For each test in batch_results["tests"]:
      - set last_batch_id = batch_results["batch_id"]
      - copy error_type, error_message, log_file, duration_ms, exit_code if present
      - if new status in {failed, retriable_error, error}: retry_count += 1
      - if new status == retriable_error AND retry_count >= max_retry:
            status = "ignored"
            ignore_reason = f"max retry exceeded for {error_type}"
        else:
            status = new_status

    For each test in handled.get("tests", []):
      apply status override + ignore_reason if present (AFTER batch_results merge).

    Recompute statistics by counting status occurrences.

    Returns the number of tests updated from batch_results.
    """
    tests = manifest.get("tests", [])
    by_id = {t.get("test_id"): t for t in tests if t.get("test_id") is not None}
    by_node = {t.get("test_node"): t for t in tests if t.get("test_node")}

    def _find(result):
        tid = result.get("test_id")
        if tid is not None and tid in by_id:
            return by_id[tid]
        node = result.get("test_node")
        if node and node in by_node:
            return by_node[node]
        return None

    updated_count = 0
    batch_id = batch_results.get("batch_id")
    for result in batch_results.get("tests", []):
        target = _find(result)
        if target is None:
            continue
        updated_count += 1
        if batch_id is not None:
            target["last_batch_id"] = batch_id
        new_status = result.get("status", target.get("status", "pending"))
        error_type = result.get("error_type")
        if error_type is not None:
            target["error_type"] = error_type
        # Copy additional fields from executor result
        for field in ("error_message", "log_file", "duration_ms", "exit_code", "run_at"):
            if field in result and result[field] is not None:
                target[field] = result[field]
        if "run_at" not in target:
            target["run_at"] = datetime.now().isoformat()

        if new_status in ("failed", "retriable_error", "error"):
            target["retry_count"] = int(target.get("retry_count", 0)) + 1

        max_retry = int(target.get("max_retry", 3))
        if new_status == "retriable_error" and target.get("retry_count", 0) >= max_retry:
            target["status"] = "ignored"
            et = target.get("error_type", error_type or "unknown")
            target["ignore_reason"] = f"max retry exceeded for {et}"
        else:
            target["status"] = new_status

    for handled_t in (handled or {}).get("tests", []):
        target = _find(handled_t)
        if target is None:
            continue
        # handled_tests status can be in "status" or "final_status"
        new_status = handled_t.get("status") or handled_t.get("final_status")
        if new_status:
            target["status"] = new_status
        if "ignore_reason" in handled_t:
            target["ignore_reason"] = handled_t["ignore_reason"]
        if "ignored_reason" in handled_t:
            target["ignore_reason"] = handled_t["ignored_reason"]
        # Copy commit hash if present (from failure-handler fix)
        if "commit" in handled_t:
            target["commit"] = handled_t["commit"]
        # Copy errors[]/failures[] history if present
        if "errors" in handled_t:
            target["errors"] = handled_t["errors"]
        if "failures" in handled_t:
            target["failures"] = handled_t["failures"]

    # Note: statistics are recalculated by save_manifest() or calculate_statistics()
    return updated_count

def update_single_status(manifest: dict, test_node: str, status: str, **kwargs) -> bool:
    """更新单个测试状态"""
    for test in manifest["tests"]:
        if test["test_node"] == test_node:
            test["status"] = status
            test["run_at"] = kwargs.get("run_at", datetime.now().isoformat())
            
            if status == "failed" or status == "error":
                test["exit_code"] = kwargs.get("exit_code", 1)
                test["error_type"] = kwargs.get("error_type", "unknown")
                test["error_message"] = kwargs.get("error_message", "")
                test["log_file"] = kwargs.get("log_file", "")
            
            if status == "ignored":
                test["ignored_reason"] = kwargs.get("ignored_reason", "")
            
            if status == "passed":
                test["exit_code"] = 0
            
            if kwargs.get("version_mismatch_related"):
                test["version_mismatch_related"] = True
            
            return True
    return False


def batch_update_status(manifest: dict, results: list) -> int:
    """批量更新状态（从结果文件）"""
    updated_count = 0
    for result in results:
        test_node = result.get("test_node")
        status = result.get("status")
        
        if test_node and status:
            kwargs = {
                "run_at": result.get("run_at"),
                "exit_code": result.get("exit_code"),
                "error_type": result.get("error_type"),
                "error_message": result.get("error_message"),
                "log_file": result.get("log_file"),
                "ignored_reason": result.get("ignored_reason"),
                "duration_ms": result.get("duration_ms"),
            }
            if update_single_status(manifest, test_node, status, **kwargs):
                updated_count += 1
    
    return updated_count


def update_from_workflow_state(
    workflow_state_path: Path,
    batch_dir: Path = None,
    batch_id: str = None
) -> dict:
    """从 workflow_state.json 读取路径并更新 manifest"""

    state = load_workflow_state(workflow_state_path)
    if "error" in state:
        return state

    paths = state.get("paths", {})
    manifest_path = Path(paths.get("manifest", ""))

    if batch_id is None:
        batch_id = state.get("current_batch", {}).get("batch_id")

    if batch_dir is None:
        batches_dir = paths.get("batches_dir")
        if not batches_dir:
            # Fallback: construct from run_dir if batches_dir not in paths
            run_dir_str = paths.get("run_dir", "")
            if run_dir_str:
                batches_dir = str(Path(run_dir_str) / "batches")
        if batches_dir and batch_id:
            batch_dir = Path(batches_dir) / batch_id

    if not manifest_path.exists():
        return {"error": f"manifest.json not found: {manifest_path}"}

    manifest = load_manifest(manifest_path)
    batch_results_data = {"tests": [], "batch_id": batch_id}
    handled_tests_data = {"tests": []}

    if batch_dir:
        batch_results_path = batch_dir / "batch_results.json"
        handled_tests_path = batch_dir / "handled_tests.json"

        if batch_results_path.exists():
            batch_results_data = json.loads(batch_results_path.read_text(encoding="utf-8"))
            # P1: Type-B fabrication backstop — stat-audit the remote pytest
            # log BEFORE consuming the per-test results into the manifest. If
            # the log doesn't exist or its size disagrees with what
            # batch_results.json claims, refuse to update. A transient
            # bastion outage is mapped to next_action=wait (NOT audit_failed)
            # so the supervisor's reconnect loop picks it up instead of the
            # workflow looping on the same batch.
            profile = (state.get("config") or {}).get("remote_server", "t_h20")
            ok, reason = audit_batch_results(batch_results_data, profile)
            if not ok:
                if reason.startswith("bastion_disconnect:"):
                    return {
                        "next_action": "wait",
                        "reason": reason,
                        "batch_id": batch_id,
                    }
                return {
                    "error": "audit_failed",
                    "reason": reason,
                    "batch_id": batch_id,
                    "raw_log_path": (batch_results_data.get("remote_log") or {}).get("raw_log_path"),
                }

        if handled_tests_path.exists():
            handled_tests_data = json.loads(handled_tests_path.read_text(encoding="utf-8"))

    # v5 merge: batch_results first, then handled_tests overrides
    updated_count = merge_batch_results(manifest, batch_results_data, handled_tests_data)
    is_valid, errors = save_manifest(manifest, manifest_path)
    if not is_valid:
        return {"error": "schema_validation_failed", "details": errors}

    return {
        "status": "updated",
        "manifest_path": str(manifest_path),
        "batch_dir": str(batch_dir) if batch_dir else None,
        "batch_id": batch_id,
        "updated_count": updated_count,
        "statistics": manifest["statistics"],
        "timestamp": datetime.now().isoformat()
    }


def generate_worker_output(update_result: dict, manifest: dict) -> dict:
    """
    生成 Worker 返回格式（符合 worker_output_schema）
    
    Args:
        update_result: 更新结果
        manifest: manifest dict
        
    Returns:
        Worker 标准输出格式
    """
    stats = manifest.get("statistics", {})
    
    return {
        "stats": {
            "passed": stats.get("passed", 0),
            "failed": stats.get("failed", 0),
            "error": stats.get("error", 0),
            "ignored": stats.get("ignored", 0),
            "pending": stats.get("pending", 0)
        },
        "next_action": "continue",
        "error": update_result.get("error") if "error" in update_result else None,
        "blocked_reason": None
    }


def main():
    parser = argparse.ArgumentParser(description="更新测试状态")
    
    # 模式1：从 workflow_state.json 读取路径
    parser.add_argument("--workflow-state", type=str,
                        help="workflow_state.json 路径")
    
    # 模式2：直接指定路径
    parser.add_argument("--manifest-path", type=str,
                        help="manifest.json 文件路径（直接指定）")
    parser.add_argument("--batch-results-path", type=str,
                        help="batch_results.json 文件路径")
    parser.add_argument("--handled-tests-path", type=str,
                        help="handled_tests.json 文件路径")
    
    # 操作模式
    parser.add_argument("--single", metavar="TEST_NODE", help="单个测试的 test_node")
    parser.add_argument("--batch", action="store_true", help="批量更新模式")
    parser.add_argument("--from-file", metavar="FILE", help="批量更新的结果文件")
    
    # 状态参数
    parser.add_argument("--status", choices=["passed", "failed", "pending", "error", "ignored"], 
                        help="要设置的状态")
    parser.add_argument("--reason", metavar="TEXT", help="设置 ignored 状态时的原因")
    parser.add_argument("--error-type", metavar="TYPE", help="错误类型 (A/B/C/D/E/M)")
    parser.add_argument("--error-message", metavar="MSG", help="错误消息")
    parser.add_argument("--log-file", metavar="PATH", help="日志文件路径")
    
    # 输出
    # Report / stats flags (ported from update_manifest.py)
    parser.add_argument("--report", action="store_true", help="generate text statistics report")
    parser.add_argument("--daily-report", action="store_true", help="generate JSON daily report")
    parser.add_argument("--recalc-stats", action="store_true", help="recalculate statistics and save")
    parser.add_argument("--version-mismatch", action="store_true", help="mark as version mismatch related")
    # --test is an alias for --single (backward compat with update_manifest.py)
    parser.add_argument("--test", metavar="TEST_NODE", dest="single", help="alias for --single")
    parser.add_argument("--dry-run", action="store_true", help="仅显示结果，不写入文件")
    parser.add_argument("--worker-output", action="store_true", 
                        help="输出 Worker 标准格式（符合 worker_output_schema）")
    
    args = parser.parse_args()
    
    # 确定路径
    if args.workflow_state:
        workflow_state_path = Path(args.workflow_state)
        state = load_workflow_state(workflow_state_path)
        if "error" in state:
            print(json.dumps(state, indent=2))
            return
        
        paths = state.get("paths", {})
        manifest_path = Path(paths.get("manifest", ""))
        batch_results_path = Path(args.batch_results_path or paths.get("batch_results", ""))
        handled_tests_path = Path(args.handled_tests_path or paths.get("handled_tests", ""))
        
    elif args.manifest_path:
        manifest_path = Path(args.manifest_path)
        batch_results_path = Path(args.batch_results_path) if args.batch_results_path else None
        handled_tests_path = Path(args.handled_tests_path) if args.handled_tests_path else None
        
    else:
        # 默认尝试读取 workflow_state.json
        # 从脚本目录推断 workflow_state.json 路径
        default_workflow_state = Path(__file__).parent.parent.parent.parent.parent / ".agents" / "workflow_state.json"
        if default_workflow_state.exists():
            state = load_workflow_state(default_workflow_state)
            if "error" not in state:
                paths = state.get("paths", {})
                manifest_path = Path(paths.get("manifest", ""))
                batch_results_path = Path(paths.get("batch_results", ""))
                handled_tests_path = Path(paths.get("handled_tests", ""))
            else:
                print(json.dumps({"error": "请指定 --workflow-state 或 --manifest-path"}, indent=2))
                return
        else:
            print(json.dumps({"error": "请指定 --workflow-state 或 --manifest-path"}, indent=2))
            return
    
    if not manifest_path.exists():
        print(json.dumps({"error": f"manifest.json not found: {manifest_path}"}, indent=2))
        return
    
    manifest = load_manifest(manifest_path)
    
    if args.report:
        # Text statistics report
        stats = calculate_statistics(manifest["tests"])
        tests = manifest.get("tests", [])
        lines = [
            "=" * 60,
            "Unit Test Statistics Report",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            "",
            f"Total tests: {stats.get('total', 0)}",
            f"Executed:   {stats.get('executed', 0)}",
            f"Progress:   {stats.get('progress', 0)}%",
            "",
            "Status breakdown:",
            f"  passed:  {stats.get('passed', 0)}",
            f"  failed:  {stats.get('failed', 0)}",
            f"  error:   {stats.get('error', 0)}",
            f"  pending: {stats.get('pending', 0)}",
            f"  ignored: {stats.get('ignored', 0)}",
            "=" * 60,
        ]
        print("\n".join(lines))
        return

    if args.daily_report:
        # JSON daily report
        stats = calculate_statistics(manifest["tests"])
        tests = manifest.get("tests", [])
        today = datetime.now().strftime("%Y-%m-%d")
        today_tests = [t for t in tests if t.get("run_at", "").startswith(today)]
        report = {
            "date": today,
            "generated_at": datetime.now().isoformat(),
            "total_tests": stats.get("total", 0),
            "executed": stats.get("executed", 0),
            "progress": stats.get("progress", 0),
            "status_breakdown": {k: v for k, v in stats.items() if k not in ("total", "executed", "progress")},
            "today": {
                "executed": len(today_tests),
                "passed": sum(1 for t in today_tests if t.get("status") == "passed"),
                "failed": sum(1 for t in today_tests if t.get("status") == "failed"),
                "error": sum(1 for t in today_tests if t.get("status") == "error"),
            },
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if args.recalc_stats:
        stats = calculate_statistics(manifest["tests"])
        manifest["statistics"] = stats
        is_valid, errors = save_manifest(manifest, manifest_path)
        if not is_valid:
            print(json.dumps({"error": "schema_validation_failed", "details": errors}, indent=2))
            return
        print(f"Statistics recalculated: {stats}")
        return

    if args.single:
        # 单个更新
        if not args.status:
            print(json.dumps({"error": "必须指定 --status"}, indent=2))
            return
        
        kwargs = {}
        if args.version_mismatch:
            kwargs["version_mismatch_related"] = True
        if args.reason:
            kwargs["ignored_reason"] = args.reason
        if args.error_type:
            kwargs["error_type"] = args.error_type
        if args.error_message:
            kwargs["error_message"] = args.error_message
        if args.log_file:
            kwargs["log_file"] = args.log_file
        
        found = update_single_status(manifest, args.single, args.status, **kwargs)
        if found:
            print(f"✓ 更新 {args.single} -> {args.status}")
        else:
            print(f"✗ 未找到测试: {args.single}")
            return
    
    elif args.batch or args.from_file:
        # 批量更新
        if args.from_file:
            results_file = Path(args.from_file)
            if not results_file.exists():
                print(json.dumps({"error": f"文件不存在: {results_file}"}, indent=2))
                return

            raw = json.loads(results_file.read_text(encoding="utf-8"))

            # P1: Type-B backstop is mandatory regardless of entry point. When
            # --from-file is given an executor-shaped payload (dict with
            # remote_log + tests), run the same stat audit before touching
            # the manifest. Skip only for legacy bare-list / handled-tests
            # payloads (no remote_log → not an executor output).
            if isinstance(raw, dict) and "tests" in raw and "remote_log" in raw:
                profile = "t_h20"
                if args.workflow_state:
                    _st = load_workflow_state(Path(args.workflow_state))
                    if "error" not in _st:
                        profile = (_st.get("config") or {}).get("remote_server", "t_h20")
                ok, reason = audit_batch_results(raw, profile)
                if not ok:
                    if reason.startswith("bastion_disconnect:"):
                        print(json.dumps(
                            {"next_action": "wait", "reason": reason}, indent=2,
                        ))
                    else:
                        print(json.dumps(
                            {"error": "audit_failed", "reason": reason}, indent=2,
                        ))
                    return

            results = raw["tests"] if isinstance(raw, dict) and "tests" in raw else raw

            count = batch_update_status(manifest, results)
            print(f"✓ 批量更新 {count} 个测试状态")
        else:
            # --batch mode: merge batch_results + handled_tests into manifest
            if args.workflow_state:
                # Recommended path: read paths from workflow_state.json,
                # find batch_dir from current_batch, run audit + v5 merge.
                update_result = update_from_workflow_state(
                    workflow_state_path
                )
                print(json.dumps(update_result, indent=2))
                return
            elif batch_results_path and batch_results_path.exists():
                # Direct path: manifest-path + batch-results-path given explicitly.
                # Read batch_results and handled_tests, run v5 merge (no audit).
                br = json.loads(batch_results_path.read_text(encoding="utf-8"))
                ht = {"tests": []}
                if handled_tests_path and handled_tests_path.exists():
                    ht = json.loads(handled_tests_path.read_text(encoding="utf-8"))
                count = merge_batch_results(manifest, br, ht)
                print(f"v5 merge: {count} tests updated")
            else:
                print(json.dumps({"error": "--batch requires --workflow-state or --batch-results-path"}, indent=2))
                return
    
    else:
        # Default mode: if --workflow-state given, use update_from_workflow_state
        # (finds batch_dir from state, runs audit + v5 merge).
        if args.workflow_state:
            update_result = update_from_workflow_state(workflow_state_path)
            if args.worker_output:
                worker_result = generate_worker_output(update_result, manifest)
                print(json.dumps(worker_result, indent=2))
            else:
                print(json.dumps(update_result, indent=2))
            return
        else:
            print(json.dumps({"error": "Specify --workflow-state (recommended) or --single/--batch/--from-file"}, indent=2))
            return
    stats = calculate_statistics(manifest["tests"])
    print("\n当前统计:")
    print(f"  Passed: {stats['passed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Error: {stats['error']}")
    print(f"  Pending: {stats['pending']}")
    print(f"  Ignored: {stats['ignored']}")
    print(f"  已执行: {stats['executed']} ({stats['progress']}%)")
    
    if args.dry_run:
        print("\n[DRY RUN] 未写入文件")
        return

    is_valid, errors = save_manifest(manifest, manifest_path)
    if not is_valid:
        print(json.dumps({"error": "schema_validation_failed", "details": errors}, indent=2))
        return
    print("\n✓ manifest.json 和 test_list.txt 已更新")


if __name__ == "__main__":
    main()