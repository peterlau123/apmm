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
"""

import json
import argparse
from datetime import datetime
from pathlib import Path

from shared.validate_schema import validate_and_write


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
        if batches_dir and batch_id:
            batch_dir = Path(batches_dir) / batch_id

    if not manifest_path.exists():
        return {"error": f"manifest.json not found: {manifest_path}"}

    manifest = load_manifest(manifest_path)
    all_results = []

    if batch_dir:
        batch_results_path = batch_dir / "batch_results.json"
        handled_tests_path = batch_dir / "handled_tests.json"

        if batch_results_path.exists():
            batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))
            all_results.extend(batch_results.get("tests", []))

        if handled_tests_path.exists():
            handled_tests = json.loads(handled_tests_path.read_text(encoding="utf-8"))
            all_results.extend(handled_tests.get("tests", []))

    updated_count = batch_update_status(manifest, all_results)
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
    
    if args.single:
        # 单个更新
        if not args.status:
            print(json.dumps({"error": "必须指定 --status"}, indent=2))
            return
        
        kwargs = {}
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
            
            results = json.loads(results_file.read_text(encoding="utf-8"))
            if isinstance(results, dict) and "tests" in results:
                results = results["tests"]
            
            count = batch_update_status(manifest, results)
            print(f"✓ 批量更新 {count} 个测试状态")
        else:
            # 从 batch_results 和 handled_tests 更新
            if batch_results_path.exists() or handled_tests_path.exists():
                update_result = update_from_workflow_state(
                    workflow_state_path or default_workflow_state,
                    batch_results_path,
                    handled_tests_path
                )
                print(json.dumps(update_result, indent=2))
            else:
                print(json.dumps({"error": "batch 和 from-file 都需要指定"}, indent=2))
                return
    
    else:
        # 默认：从 batch_results 和 handled_tests 更新
        if batch_results_path.exists() or handled_tests_path.exists():
            update_result = update_from_workflow_state(
                workflow_state_path or default_workflow_state,
                batch_results_path,
                handled_tests_path
            )
            if args.worker_output:
                worker_result = generate_worker_output(update_result, manifest)
                print(json.dumps(worker_result, indent=2))
            else:
                print(json.dumps(update_result, indent=2))
            return
        else:
            print(json.dumps({"error": "请指定操作模式 (--single, --batch, --from-file)"}, indent=2))
            return
    
    # 显示统计
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