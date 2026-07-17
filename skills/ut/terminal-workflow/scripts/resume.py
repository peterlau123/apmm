#!/usr/bin/env python3
"""resume.py - 分析 workflow_state.json，输出 resume 建议

只分析状态，不执行任何操作。
"""

import json
import argparse
from pathlib import Path
import sys
import os

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.ut_common.workflow_state_manager import load_workflow_state


def analyze_intermediate_batches(workflow_state_path: Path) -> list:
    """分析中间状态 batch（有 config 无 results）"""
    state = load_workflow_state(workflow_state_path)
    paths = state.get("paths", {})
    batches_dir = Path(paths.get("batches_dir", ""))
    if not batches_dir.exists():
        return []

    intermediate = []
    for batch_dir in batches_dir.iterdir():
        if not batch_dir.is_dir():
            continue
        config_path = batch_dir / "batch_config.json"
        results_path = batch_dir / "batch_results.json"
        if config_path.exists() and not results_path.exists():
            intermediate.append(batch_dir.name)
    return intermediate


def analyze_resume_state(workflow_state_path: Path) -> dict:
    """分析 workflow_state.json，输出 resume 建议"""
    state = load_workflow_state(workflow_state_path)
    resume_info = state.get("resume_info", {})
    batch_stats = state.get("batch_stats", {})
    test_stats = state.get("test_stats", {})
    intermediate = analyze_intermediate_batches(workflow_state_path)

    print("=" * 60)
    print("WORKFLOW RESUME ANALYSIS")
    print("=" * 60)
    print(f"Last Batch ID: {resume_info.get('last_batch_id')}")
    print(f"Last Batch Status: {resume_info.get('last_batch_status')}")
    print(f"Pending Batches: {resume_info.get('pending_batches_count')}")
    print(f"Can Resume: {resume_info.get('can_resume')}")
    print(f"Recommendation: {resume_info.get('resume_recommendation')}")
    print("")
    print("Batch Stats:")
    for key, value in batch_stats.items():
        print(f"  {key}: {value}")
    print("")
    print("Test Stats:")
    for key, value in test_stats.items():
        print(f"  {key}: {value}")
    print("")
    if intermediate:
        print(f"[WARN] 发现 {len(intermediate)} 个中间状态 batch:")
        for batch_id in intermediate:
            print(f"  - {batch_id}")
        print("\n建议处理方式:")
        print("  A. 批量重新执行")
        print("  B. 标记为 'failed'")
        print("  C. 忽略")
    print("=" * 60)
    return resume_info


def main():
    parser = argparse.ArgumentParser(description="分析 workflow_state.json，输出 resume 建议")
    parser.add_argument("--workflow-state", required=True, help="workflow_state.json 路径")
    args = parser.parse_args()
    analyze_resume_state(Path(args.workflow_state))


if __name__ == "__main__":
    main()