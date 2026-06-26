"""
Failure Handler - 分析失败原因脚本

支持两种模式：
1. 从 workflow_state.json 读取路径（推荐）
2. 从命令行参数直接指定路径

读取 batch_results.json，分类失败测试

NOTE: PYTHONPATH must be cleared before importing any project modules to avoid
Hermes venv leaking into apmm subprocesses (fake 'jsonschema not installed').
"""

import argparse
import importlib.util
import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime

# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']


def _load_branch_checker():
    """Lazy-load skills/ut/workflow/scripts/check_vllm_branch.py."""
    p = (
        Path(__file__).resolve().parents[2]
        / "workflow"
        / "scripts"
        / "check_vllm_branch.py"
    )
    spec = importlib.util.spec_from_file_location("ut_fh_check_vllm_branch", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ensure_on_branch(expected: str, repo_path: str) -> None:
    """Indirection so tests can patch this symbol on the analyze_failures module."""
    _load_branch_checker().ensure_on_branch(expected, repo_path)


def load_workflow_state(workflow_state_path: Path) -> dict:
    """从 workflow_state.json 加载配置"""
    if not workflow_state_path.exists():
        return {"error": f"workflow_state.json not found: {workflow_state_path}"}
    return json.loads(workflow_state_path.read_text(encoding="utf-8"))


# 失败分类规则 - 6种类型
FAILURE_CLASSES = {
    "dependency": {
        "name": "依赖缺失",
        "patterns": [
            r"ImportError:",
            r"ModuleNotFoundError:",
            r"No module named",
        ],
        # 2026-06-23: dependency-resolver gateway 不存在；显式 ModuleNotFoundError
        # 类依赖缺失走 M2 Option E 路径 → final_status=ignored，由人工处理。与
        # tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md §2 D14 一致。
        "handler": "mark_ignored",
        "retry": False
    },
    "network": {
        "name": "网络超时",
        "patterns": [
            r"ConnectionError",
            r"TimeoutError",
            r"HTTPConnectionPool",
            r"Read timed out",
            r"Connection refused",
        ],
        "handler": "retry_with_mirror",
        "retry": True
    },
    "resource": {
        "name": "资源不足",
        "patterns": [
            r"OutOfMemoryError",
            r"CUDA out of memory",
            r"OOM",
            r"Resource temporarily unavailable",
            r"No GPUs available",
        ],
        "handler": "pause_batch",
        "retry": False
    },
    "version": {
        "name": "版本不兼容",
        "patterns": [
            r"requires pytest",
            r"incompatible version",
            r"TypeError.*argument",
            r"AttributeError.*torch",
            r"Torch not compiled with",
        ],
        "handler": "mark_ignored",
        "retry": False
    },
    "functional": {
        "name": "功能逻辑问题",
        "patterns": [
            r"AssertionError",
            r"RuntimeError:.*vllm",
            r"ValueError:.*invalid",
            r"FAILED",
        ],
        "handler": "keep_failed",
        "retry": False
    },
    "unknown": {
        "name": "其他未知",
        "patterns": [],
        "handler": "extract_info",
        "retry": True
    }
}


def classify_failure(error_message: str) -> dict:
    """
    分类失败原因
    
    Returns:
        dict: {"class": "...", "name": "...", "matched_pattern": "..."}
    """
    for class_id, info in FAILURE_CLASSES.items():
        for pattern in info["patterns"]:
            if re.search(pattern, error_message, re.IGNORECASE):
                return {
                    "class": class_id,
                    "class_name": info["name"],
                    "matched_pattern": pattern,
                    "handler": info["handler"],
                    "retry": info["retry"],
                    "error_preview": error_message[:200],
                    "timestamp": datetime.now().isoformat()
                }
    
    # 默认返回 unknown
    return {
        "class": "unknown",
        "class_name": "其他未知",
        "handler": "extract_info",
        "retry": True,
        "error_preview": error_message[:200],
        "timestamp": datetime.now().isoformat()
    }


def filter_processable(tests: list) -> list:
    """v5: keep only tests in {failed, error}. Skip retriable_error and others."""
    return [t for t in tests if t.get("status") in ("failed", "error")]


def resolve_remote_log(test: dict, run_dir: Path) -> dict | None:
    """v5: resolve a test's last_batch_id -> batch_results.json.remote_log.

    Returns the remote_log dict, or None when last_batch_id is missing or the
    batch_results.json file is missing / unreadable / has no remote_log.
    """
    bid = test.get("last_batch_id")
    if not bid:
        return None
    p = Path(run_dir) / str(bid) / "batch_results.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("remote_log")


def analyze_batch_results(batch_results_file: Path) -> dict:
    """
    分析批次测试结果
    
    Args:
        batch_results_file: batch_results.json 文件路径
        
    Returns:
        dict: 分析结果
    """
    if not batch_results_file.exists():
        return {"error": f"batch_results.json not found: {batch_results_file}"}
    
    results = json.loads(batch_results_file.read_text(encoding="utf-8"))
    
    analyzed = {
        "batch_id": results.get("batch_id"),
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "failures_by_class": {},
        "tests": []
    }
    
    # 统计各测试结果
    for test in results.get("tests", []):
        analyzed["total_tests"] += 1
        status = test.get("status")
        
        if status == "passed":
            analyzed["passed"] += 1
        elif status == "failed":
            analyzed["failed"] += 1
            # 分类失败原因
            error_msg = test.get("error_message", "")
            classification = classify_failure(error_msg)
            test["classification"] = classification
            
            # 按类别统计
            class_id = classification["class"]
            if class_id not in analyzed["failures_by_class"]:
                analyzed["failures_by_class"][class_id] = {
                    "name": classification["class_name"],
                    "count": 0,
                    "tests": []
                }
            analyzed["failures_by_class"][class_id]["count"] += 1
            analyzed["failures_by_class"][class_id]["tests"].append(test.get("test_node"))
            
            analyzed["tests"].append(test)
        elif status == "error":
            analyzed["error"] += 1
            analyzed["tests"].append(test)
    
    analyzed["timestamp"] = datetime.now().isoformat()
    return analyzed


def analyze_from_workflow_state(workflow_state_path: Path, output_path: Path = None) -> dict:
    """
    从 workflow_state.json 读取 batch_results.json 路径并分析
    
    Args:
        workflow_state_path: workflow_state.json 文件路径
        output_path: 输出文件路径
        
    Returns:
        分析结果 dict
    """
    state = load_workflow_state(workflow_state_path)
    if "error" in state:
        return state
    
    paths = state.get("paths", {})
    batch_results_path = Path(paths.get("batch_results", ""))
    
    if not batch_results_path:
        return {"error": "batch_results path not found in workflow_state.json"}
    
    if not batch_results_path.exists():
        return {"error": f"batch_results.json not found: {batch_results_path}"}
    
    result = analyze_batch_results(batch_results_path)
    
    # 写入输出文件
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"[OK] Analysis saved to: {output_path}")
    
    return result


def analyze_failed_tests_v5(
    tests: list,
    *,
    run_dir: Path | None = None,
    vllm_repo_path: str = "/gpfs/gcsp/M2.7_verify/vllm",
    expected_branch: str = "2.5.1_ut_verify",
    check_branch: bool = True,
) -> list:
    """v5 entry: pre-flight branch check, filter to processable, attach remote_log.

    1. ensure_on_branch(expected_branch, vllm_repo_path) — refuses to proceed
       unless the remote vLLM repo is on the configured auto-fix branch.
       Skipped when check_branch is False (offline/test contexts).
    2. filter_processable() — drop retriable_error / passed / other; keep
       only failed + error.
    3. For each kept test, attach 'remote_log' resolved via last_batch_id when
       run_dir is provided.
    """
    if check_branch:
        ensure_on_branch(expected_branch, vllm_repo_path)
    processable = filter_processable(tests)
    if run_dir is not None:
        for t in processable:
            rl = resolve_remote_log(t, run_dir)
            if rl is not None:
                t.setdefault("remote_log", rl)
    return processable


def generate_worker_output(analyzed_result: dict) -> dict:
    """
    生成 Worker 返回格式（符合 worker_output_schema）
    
    Args:
        analyzed_result: 分析结果
        
    Returns:
        Worker 标准输出格式
    """
    # 根据 failure 分类决定 next_action
    failures_by_class = analyzed_result.get("failures_by_class", {})
    
    next_action = "continue"
    blocked_reason = None
    error = None
    
    # 资源不足 → pause
    if "resource" in failures_by_class and failures_by_class["resource"]["count"] > 0:
        next_action = "pause"
        blocked_reason = "资源不足 (OOM/GPU不足)"
    
    return {
        "stats": {
            "passed": analyzed_result.get("passed", 0),
            "failed": analyzed_result.get("failed", 0),
            "error": analyzed_result.get("error", 0),
            "ignored": 0,
            "pending": 0
        },
        "next_action": next_action,
        "error": error,
        "blocked_reason": blocked_reason
    }


def main():
    parser = argparse.ArgumentParser(description="Failure Handler - 分析失败原因")
    
    # 模式1：从 workflow_state.json 读取路径
    parser.add_argument("--workflow-state", type=str,
                        help="workflow_state.json 路径（从中读取 batch_results 路径）")
    
    # 模式2：直接指定 batch_results.json
    parser.add_argument("--batch-results", type=str,
                        help="batch_results.json 文件路径（直接指定）")
    
    # 输出
    parser.add_argument("--output", type=str, default=None,
                        help="输出文件路径（默认 stdout）")
    parser.add_argument("--worker-output", action="store_true",
                        help="输出 Worker 标准格式（符合 worker_output_schema）")
    
    args = parser.parse_args()
    
    output_path = Path(args.output) if args.output else None
    
    if args.workflow_state:
        # 模式1：从 workflow_state.json 读取
        workflow_state_path = Path(args.workflow_state)
        result = analyze_from_workflow_state(workflow_state_path, output_path)
        
    elif args.batch_results:
        # 模式2：直接指定 batch_results.json
        batch_results_file = Path(args.batch_results)
        result = analyze_batch_results(batch_results_file)
        
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"[OK] Analysis saved to: {output_path}")
        
    else:
        # 默认：从脚本目录推断 workflow_state.json 路径
        default_workflow_state = Path(__file__).parent.parent.parent.parent.parent / ".agents" / "workflow_state.json"
        if default_workflow_state.exists():
            result = analyze_from_workflow_state(default_workflow_state, output_path)
        else:
            result = {"error": "请指定 --workflow-state 或 --batch-results"}
    
    # 输出结果
    if args.worker_output:
        worker_result = generate_worker_output(result)
        print(json.dumps(worker_result, indent=2))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()