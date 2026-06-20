#!/usr/bin/env python3
"""
更新 manifest.json 的测试状态和统计信息

功能：
1. 批量更新测试状态（批次运行后调用）
2. 更新单个测试状态和错误信息
3. 自动计算并更新 statistics
4. 支持标记 version_mismatch_related

使用方法：
    python update_manifest.py --batch result.json
    python update_manifest.py --test "tests/xxx.py::test_func" --status failed
    python update_manifest.py --report
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, List, Any

# 路径配置（相对于 test_analysis 目录）
TEST_ANALYSIS_DIR = Path(__file__).parent.parent.parent.parent / "tasks" / "ut" / "test_analysis"
MANIFEST_FILE = TEST_ANALYSIS_DIR / "manifest.json"
BACKUP_DIR = TEST_ANALYSIS_DIR / "archive"


def load_manifest() -> Dict:
    """加载 manifest.json"""
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"Manifest 文件不存在: {MANIFEST_FILE}")
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def save_manifest(manifest: Dict, backup: bool = True):
    """保存 manifest.json"""
    if backup:
        backup_manifest()
    
    manifest["generated_at"] = datetime.now().isoformat()
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def backup_manifest():
    """备份当前 manifest"""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"manifest_{timestamp}.json"
    
    if MANIFEST_FILE.exists():
        import shutil
        shutil.copy2(MANIFEST_FILE, backup_file)
        backups = sorted(BACKUP_DIR.glob("manifest_*.json"))
        for old in backups[:-10]:
            old.unlink()


def calculate_statistics(tests: List[Dict]) -> Dict:
    """计算 statistics"""
    stats = defaultdict(int)

    for test in tests:
        status = test.get("status", "pending")
        stats[status] += 1

    total = len(tests)
    executed = total - stats.get("pending", 0)
    progress = (executed / total * 100) if total > 0 else 0.0

    stats["total"] = total
    stats["executed"] = executed
    stats["progress"] = round(progress, 2)

    return dict(stats)


# v5 merge ---------------------------------------------------------------

def update_manifest(manifest: Dict, batch_results: Dict, handled: Dict) -> Dict:
    """v5 manifest merge.

    For each test in batch_results["tests"]:
      - set last_batch_id = batch_results["batch_id"]
      - copy error_type if present
      - if new status in {failed, retriable_error, error}: retry_count += 1
      - if new status == retriable_error AND retry_count >= max_retry:
            status = "ignored"
            ignore_reason = f"max retry exceeded for {error_type}"
        else:
            status = new_status

    For each test in handled.get("tests", []):
      apply status override + ignore_reason if present.

    Recompute statistics by counting status occurrences (and add total /
    executed / progress derived fields).
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

    batch_id = batch_results.get("batch_id")
    for result in batch_results.get("tests", []):
        target = _find(result)
        if target is None:
            continue
        if batch_id is not None:
            target["last_batch_id"] = batch_id
        new_status = result.get("status", target.get("status", "pending"))
        error_type = result.get("error_type")
        if error_type is not None:
            target["error_type"] = error_type

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
        if "status" in handled_t:
            target["status"] = handled_t["status"]
        if "ignore_reason" in handled_t:
            target["ignore_reason"] = handled_t["ignore_reason"]

    manifest["statistics"] = calculate_statistics(tests)
    return manifest


def update_test_status(
    manifest: Dict,
    test_node: str,
    status: str,
    error_message: Optional[str] = None,
    failed_message: Optional[str] = None,
    ignored_reason: Optional[str] = None,
    version_mismatch_related: bool = False,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
    log_file: Optional[str] = None,
    run_at: Optional[str] = None
) -> bool:
    """更新单个测试状态"""
    tests = manifest.get("tests", [])
    found = False
    
    for test in tests:
        if test.get("test_node") == test_node:
            found = True
            test["status"] = status
            
            if error_message is not None:
                test["error_message"] = error_message
            if failed_message is not None:
                test["failed_message"] = failed_message
            if ignored_reason is not None:
                test["ignored_reason"] = ignored_reason
            
            test["version_mismatch_related"] = version_mismatch_related
            
            if duration_ms is not None:
                test["duration_ms"] = duration_ms
            if exit_code is not None:
                test["exit_code"] = exit_code
            if log_file is not None:
                test["log_file"] = log_file
            if run_at is not None:
                test["run_at"] = run_at
            else:
                test["run_at"] = datetime.now().isoformat()
            
            break
    
    return found


def batch_update_from_results(manifest: Dict, results: List[Dict]) -> int:
    """从结果列表批量更新"""
    updated = 0
    
    for result in results:
        test_node = result.get("test_node", "")
        if not test_node:
            continue
        
        status = result.get("status", "pending")
        error_message = result.get("error_message")
        failed_message = result.get("failed_message")
        version_mismatch = result.get("version_mismatch_related", False)
        duration_ms = result.get("duration_ms")
        exit_code = result.get("exit_code")
        log_file = result.get("log_file")
        
        if update_test_status(
            manifest, test_node, status,
            error_message=error_message,
            failed_message=failed_message,
            version_mismatch_related=version_mismatch,
            duration_ms=duration_ms,
            exit_code=exit_code,
            log_file=log_file
        ):
            updated += 1
    
    return updated


def generate_report(manifest: Dict) -> str:
    """生成统计报告"""
    stats = calculate_statistics(manifest.get("tests", []))
    tests = manifest.get("tests", [])
    
    version_mismatch_count = sum(
        1 for t in tests if t.get("version_mismatch_related", False)
    )
    
    lines = [
        "=" * 60,
        "单元测试统计报告",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        f"总测试用例数: {stats.get('total', 0)}",
        f"已执行用例数: {stats.get('executed', 0)}",
        f"进度: {stats.get('progress', 0):.2f}%",
        "",
        "状态分布:",
        f"  - passed: {stats.get('passed', 0)}",
        f"  - failed: {stats.get('failed', 0)}",
        f"  - error: {stats.get('error', 0)}",
        f"  - pending: {stats.get('pending', 0)}",
        f"  - todo: {stats.get('todo', 0)}",
        "",
        f"版本错配相关: {version_mismatch_count}",
        "",
        "=" * 60,
    ]
    
    return "\n".join(lines)


def generate_daily_report(manifest: Dict) -> Dict:
    """生成每日统计报告（JSON格式）"""
    tests = manifest.get("tests", [])
    stats = calculate_statistics(tests)
    
    today = datetime.now().strftime("%Y-%m-%d")
    today_tests = [
        t for t in tests
        if t.get("run_at") and str(t.get("run_at", "")).startswith(today)
    ]
    
    today_passed = sum(1 for t in today_tests if t.get("status") == "passed")
    today_failed = sum(1 for t in today_tests if t.get("status") == "failed")
    today_error = sum(1 for t in today_tests if t.get("status") == "error")
    
    return {
        "date": today,
        "generated_at": datetime.now().isoformat(),
        "total_tests": stats.get("total", 0),
        "executed": stats.get("executed", 0),
        "progress": stats.get("progress", 0),
        "status_breakdown": {
            "passed": stats.get("passed", 0),
            "failed": stats.get("failed", 0),
            "error": stats.get("error", 0),
            "pending": stats.get("pending", 0),
            "todo": stats.get("todo", 0)
        },
        "today": {
            "executed": len(today_tests),
            "passed": today_passed,
            "failed": today_failed,
            "error": today_error
        },
        "version_mismatch_related": sum(
            1 for t in tests if t.get("version_mismatch_related", False)
        )
    }


def main():
    parser = argparse.ArgumentParser(description="更新 manifest.json 测试状态")
    
    parser.add_argument("--batch", type=str, help="批量更新，从 JSON 文件读取结果")
    parser.add_argument("--test", type=str, help="更新单个测试，指定 test_node")
    parser.add_argument("--recalc-stats", action="store_true", help="重新计算统计信息")
    parser.add_argument("--report", action="store_true", help="生成统计报告")
    parser.add_argument("--daily-report", action="store_true", help="生成每日统计（JSON格式）")
    
    parser.add_argument("--status", type=str, help="测试状态")
    parser.add_argument("--error-message", type=str, help="错误信息")
    parser.add_argument("--failed-message", type=str, help="失败信息")
    parser.add_argument("--ignored-reason", type=str, help="忽略原因（status=ignored时必填）")
    parser.add_argument("--version-mismatch", action="store_true", help="标记为版本错配相关")
    parser.add_argument("--duration", type=int, help="执行时长（毫秒）")
    parser.add_argument("--exit-code", type=int, help="pytest 退出码")
    parser.add_argument("--log-file", type=str, help="日志文件路径")
    
    args = parser.parse_args()
    manifest = load_manifest()
    
    if args.recalc_stats:
        stats = calculate_statistics(manifest.get("tests", []))
        manifest["statistics"] = stats
        save_manifest(manifest)
        print(f"统计信息已更新: {stats}")
        return
    
    if args.report:
        report = generate_report(manifest)
        print(report)
        return
    
    if args.daily_report:
        report = generate_daily_report(manifest)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    
    if args.batch:
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"错误: 文件不存在 - {batch_file}")
            return
        
        results = json.loads(batch_file.read_text(encoding="utf-8"))
        if isinstance(results, dict) and "tests" in results:
            results = results["tests"]
        
        updated = batch_update_from_results(manifest, results)
        stats = calculate_statistics(manifest.get("tests", []))
        manifest["statistics"] = stats
        save_manifest(manifest)
        
        print(f"批量更新完成: {updated} 个测试")
        print(f"统计: {stats}")
        return
    
    if args.test:
        if not args.status:
            print("错误: 更新单个测试需要 --status 参数")
            return
        
        found = update_test_status(
            manifest, args.test, args.status,
            error_message=args.error_message,
            failed_message=args.failed_message,
            ignored_reason=args.ignored_reason,
            version_mismatch_related=args.version_mismatch,
            duration_ms=args.duration,
            exit_code=args.exit_code,
            log_file=args.log_file
        )
        
        if found:
            stats = calculate_statistics(manifest.get("tests", []))
            manifest["statistics"] = stats
            save_manifest(manifest)
            print(f"已更新: {args.test} -> {args.status}")
            print(f"统计: {stats}")
        else:
            print(f"未找到测试: {args.test}")
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()