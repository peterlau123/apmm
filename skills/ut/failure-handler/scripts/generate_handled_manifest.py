"""
Failure Handler - 生成已处理 manifest

支持两种模式：
1. 从 workflow_state.json 读取路径（推荐）
2. 从命令行参数直接指定路径

输出 handled_tests.json 到批次子目录：{run_dir}/batches/{batch_id}/handled_tests.json

用法：
    python generate_handled_manifest.py --workflow-state PATH --batch-dir PATH
    python generate_handled_manifest.py --batch-results PATH --batch-dir PATH --batch-id ID
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
from shared.validate_schema import validate_and_write


def load_workflow_state(workflow_state_path: Path) -> dict:
    """从 workflow_state.json 加载配置"""
    if not workflow_state_path.exists():
        return {"error": f"workflow_state.json not found: {workflow_state_path}"}
    return json.loads(workflow_state_path.read_text(encoding="utf-8"))


def load_batch_results(batch_results_path: Path) -> dict:
    """加载 batch_results.json"""
    if not batch_results_path.exists():
        return {"error": f"batch_results.json not found: {batch_results_path}"}
    return json.loads(batch_results_path.read_text(encoding="utf-8"))


def classify_error(error_message: str) -> str:
    """分类错误类型"""
    error_lower = error_message.lower()

    if any(k in error_lower for k in ["importerror", "modulenotfound", "no module named"]):
        return "dependency"
    if any(k in error_lower for k in ["timeout", "connectionerror", "503", "404"]):
        return "network"
    if any(k in error_lower for k in ["cuda out of memory", "oom", "gpu"]):
        return "resource"
    if any(k in error_lower for k in ["typeerror", "attributeerror", "deprecated"]):
        return "version"
    if any(k in error_lower for k in ["assertionerror", "valueerror", "expected"]):
        return "functional"
    if any(k in error_lower for k in ["failed to download", "model not found"]):
        return "download_error"

    return "other"


def generate_handled_manifest(
    batch_id: str,
    batch_results_path: Path,
    batch_dir: Path = None
) -> dict:
    """生成 handled_tests.json"""

    batch_results = load_batch_results(batch_results_path)
    if "error" in batch_results:
        return batch_results

    handled_manifest = {
        "batch_id": batch_id,
        "generated_at": datetime.now().isoformat(),
        "tests": [],
        "stats": {
            "passed": 0,
            "failed": 0,
            "ignored": 0,
            "error": 0,
            "pending": 0
        }
    }

    for test in batch_results.get("tests", []):
        status = test.get("status", "")
        if status not in ["failed", "error"]:
            continue

        test_node = test.get("test_node")
        error_message = test.get("error_message", "")[:500]
        error_type = test.get("error_type") or classify_error(error_message)

        # 根据错误类型决定处理方式
        if error_type in ["dependency", "download_error"]:
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "pending",
                "error_type": error_type,
                "error_message": error_message,
                "action": "dependency_resolver"
            })
            handled_manifest["stats"]["pending"] += 1

        elif error_type == "network":
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "ignored",
                "error_type": error_type,
                "error_message": error_message,
                "ignored_reason": "network timeout"
            })
            handled_manifest["stats"]["ignored"] += 1

        elif error_type == "resource":
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "pending",
                "error_type": error_type,
                "error_message": error_message,
                "action": "wait_resource"
            })
            handled_manifest["stats"]["pending"] += 1

        elif error_type == "version":
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "ignored",
                "error_type": error_type,
                "error_message": error_message,
                "ignored_reason": "version incompatible"
            })
            handled_manifest["stats"]["ignored"] += 1

        elif error_type == "functional":
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "failed",
                "error_type": error_type,
                "error_message": error_message,
                "action": "investigate"
            })
            handled_manifest["stats"]["failed"] += 1

        else:
            handled_manifest["tests"].append({
                "test_node": test_node,
                "final_status": "ignored",
                "error_type": error_type,
                "error_message": error_message,
                "ignored_reason": "other error"
            })
            handled_manifest["stats"]["ignored"] += 1

    # 写入输出文件到批次目录
    if batch_dir:
        batch_dir.mkdir(parents=True, exist_ok=True)
        output_path = batch_dir / "handled_tests.json"
        # 校验后写入
        is_valid, errors = validate_and_write(handled_manifest, "handled_tests", output_path)
        if not is_valid:
            return {"error": "schema_validation_failed", "details": errors}
        print(f"[OK] handled_tests.json 已保存到: {output_path}")
        handled_manifest["handled_tests_path"] = str(output_path)

    return handled_manifest


def generate_handled_manifest_from_workflow_state(
    workflow_state_path: Path,
    batch_dir: Path = None,
    batch_id: str = None
) -> dict:
    """从 workflow_state.json 读取路径并生成 handled_manifest"""

    state = load_workflow_state(workflow_state_path)
    if "error" in state:
        return state

    paths = state.get("paths", {})

    if batch_id is None:
        batch_id = state.get("current_batch", {}).get("batch_id")
        if not batch_id:
            return {"error": "batch_id not found in workflow_state.json"}

    if batch_dir is None:
        batches_dir = paths.get("batches_dir")
        if batches_dir:
            batch_dir = Path(batches_dir) / batch_id

    if batch_dir:
        batch_results_path = batch_dir / "batch_results.json"
    else:
        return {"error": "无法确定 batch_results.json 路径"}

    return generate_handled_manifest(
        batch_id=batch_id,
        batch_results_path=batch_results_path,
        batch_dir=batch_dir
    )


def generate_worker_output(handled_manifest: dict) -> dict:
    """生成 Worker 返回格式（符合 worker_output_schema）"""
    stats = handled_manifest.get("stats", {})

    next_action = "continue"
    blocked_reason = None

    for test in handled_manifest.get("tests", []):
        if test.get("error_type") == "resource" and test.get("final_status") == "pending":
            next_action = "pause"
            blocked_reason = "资源不足，需要等待"
            break

    return {
        "stats": {
            "passed": stats.get("passed", 0),
            "failed": stats.get("failed", 0),
            "error": stats.get("error", 0),
            "ignored": stats.get("ignored", 0),
            "pending": stats.get("pending", 0)
        },
        "next_action": next_action,
        "error": None,
        "blocked_reason": blocked_reason
    }


def main():
    parser = argparse.ArgumentParser(description="Failure Handler - 生成已处理 manifest")

    parser.add_argument("--workflow-state", type=str, help="workflow_state.json 路径")
    parser.add_argument("--batch-dir", type=str, help="批次目录路径")
    parser.add_argument("--batch-results", type=str, help="batch_results.json 路径")
    parser.add_argument("--batch-id", type=str, help="批次 ID")
    parser.add_argument("--worker-output", action="store_true", help="输出 Worker 标准格式")

    args = parser.parse_args()

    if args.workflow_state:
        workflow_state_path = Path(args.workflow_state)
        batch_dir = Path(args.batch_dir) if args.batch_dir else None
        batch_id = args.batch_id

        result = generate_handled_manifest_from_workflow_state(
            workflow_state_path=workflow_state_path,
            batch_dir=batch_dir,
            batch_id=batch_id
        )

    elif args.batch_results:
        batch_results_path = Path(args.batch_results)
        batch_dir = Path(args.batch_dir) if args.batch_dir else None
        batch_id = args.batch_id or "unknown"

        result = generate_handled_manifest(
            batch_id=batch_id,
            batch_results_path=batch_results_path,
            batch_dir=batch_dir
        )

    else:
        result = {"error": "请指定 --workflow-state 或 --batch-results"}

    if args.worker_output:
        worker_result = generate_worker_output(result)
        print(json.dumps(worker_result, indent=2))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()