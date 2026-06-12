#!/usr/bin/env python3
"""
Supervisor 辅助脚本（可选）

**注意**: v5.0 后，主循环逻辑已移至 SKILL.md 内联执行。
此脚本保留作为辅助工具，用于：
- 状态检查和验证
- 调试测试
- 单次迭代模式（用于调试）

推荐执行方式：
- 主要方式：加载 ut/workflow skill（Agent 内联执行）
- 辅助方式：此脚本（用于调试/测试）

用法：
    python supervisor_loop.py --check           # 检查当前状态
    python supervisor_loop.py --validate        # 校验 workflow.yaml
    python supervisor_loop.py --update-stats    # 从 manifest 更新 stats
"""

import json
import yaml
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# 添加共享模块路径
SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from shared.config_loader import (
    load_workflow_state,
    get_paths,
    load_workflow_yaml,
    get_current_run
)
from shared.validate_schema import validate_yaml

# 默认配置
DEFAULT_WORKFLOW_YAML = SKILL_DIR.parent.parent / ".agents" / "workflow.yaml"


def write_json(file_path: Path, data: Any) -> None:
    """写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def read_json(file_path: Path) -> Dict:
    """读取 JSON 文件"""
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def check_current_state(workflow_state_path: Path = None) -> Dict:
    """检查当前 workflow 状态"""
    if workflow_state_path is None:
        current_run = get_current_run()
        if current_run and current_run.get("workflow_state_path"):
            workflow_state_path = Path(current_run["workflow_state_path"])
        else:
            return {"error": "无法找到 workflow_state.json"}

    if not workflow_state_path.exists():
        return {"error": f"文件不存在: {workflow_state_path}"}

    state = read_json(workflow_state_path)

    return {
        "workflow": state.get("workflow", {}),
        "current_stage": state.get("current_stage"),
        "iteration": state.get("iteration", 0),
        "stats": state.get("stats", {}),
        "flags": state.get("flags", {}),
        "paths": {
            "run_dir": state.get("paths", {}).get("run_dir"),
            "manifest": state.get("paths", {}).get("manifest"),
        },
        "last_update": state.get("last_update")
    }


def validate_workflow_config(workflow_yaml_path: Path) -> Dict:
    """校验 workflow.yaml 配置"""
    if not workflow_yaml_path.exists():
        return {"valid": False, "error": f"文件不存在: {workflow_yaml_path}"}

    is_valid, errors = validate_yaml(workflow_yaml_path, "workflow")

    if is_valid:
        config = load_workflow_yaml(workflow_yaml_path)
        stages = config.get("stages", [])  # 注意：stages 是顶级字段

        return {
            "valid": True,
            "workflow_name": config.get("workflow", {}).get("name"),
            "stages_count": len(stages),
            "loop_stages": config.get("loop", {}).get("stages", []),
        }
    else:
        return {"valid": False, "errors": errors}


def update_stats_from_manifest(workflow_state_path: Path) -> Dict:
    """从 manifest.json 更新 stats"""
    state = read_json(workflow_state_path)
    manifest_path = Path(state.get("paths", {}).get("manifest", ""))

    if not manifest_path.exists():
        return {"error": f"manifest.json 不存在: {manifest_path}"}

    manifest = read_json(manifest_path)
    statistics = manifest.get("statistics", {})

    state["stats"] = statistics
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    write_json(workflow_state_path, state)

    return {"updated": True, "stats": statistics}


def print_status_summary(state: Dict) -> None:
    """打印状态摘要"""
    print("\n" + "="*60)
    print("Workflow 状态摘要")
    print("="*60)

    workflow = state.get("workflow", {})
    print(f"名称: {workflow.get('name', 'N/A')}")
    print(f"状态: {workflow.get('status', 'N/A')}")
    print(f"当前 Stage: {state.get('current_stage', 'N/A')}")
    print(f"迭代次数: {state.get('iteration', 0)}")

    stats = state.get("stats", {})
    print(f"\n统计:")
    print(f"  - pending: {stats.get('pending', 0)}")
    print(f"  - passed: {stats.get('passed', 0)}")
    print(f"  - failed: {stats.get('failed', 0)}")
    print(f"  - error: {stats.get('error', 0)}")

    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Supervisor 辅助脚本")

    parser.add_argument("--workflow-yaml", type=str, default=str(DEFAULT_WORKFLOW_YAML))
    parser.add_argument("--workflow-state", type=str, default=None)
    parser.add_argument("--check", action="store_true", help="检查当前状态")
    parser.add_argument("--validate", action="store_true", help="校验 workflow.yaml")
    parser.add_argument("--update-stats", action="store_true", help="从 manifest 更新 stats")

    args = parser.parse_args()
    workflow_yaml_path = Path(args.workflow_yaml)
    workflow_state_path = Path(args.workflow_state) if args.workflow_state else None

    if args.check:
        state = check_current_state(workflow_state_path)
        if "error" in state:
            print(f"[ERROR] {state['error']}")
        else:
            print_status_summary(state)

    elif args.validate:
        result = validate_workflow_config(workflow_yaml_path)
        if result.get("valid"):
            print("[OK] workflow.yaml 校验通过")
            print(f"  - workflow: {result.get('workflow_name')}")
            print(f"  - stages: {result.get('stages_count')}")
        else:
            print("[ERROR] workflow.yaml 校验失败")
            for error in result.get("errors", []):
                print(f"  - {error}")

    elif args.update_stats:
        current_run = get_current_run()
        if current_run and current_run.get("workflow_state_path"):
            workflow_state_path = Path(current_run["workflow_state_path"])
        result = update_stats_from_manifest(workflow_state_path)
        if result.get("updated"):
            print("[OK] stats 已更新")
        else:
            print(f"[ERROR] {result.get('error')}")

    else:
        print("Supervisor 辅助脚本（可选）")
        print("\n推荐：加载 ut/workflow skill（Agent 内联执行）")
        print("\n命令：")
        print("  --check           检查当前状态")
        print("  --validate        校验 workflow.yaml")
        print("  --update-stats    从 manifest 更新 stats")


if __name__ == "__main__":
    main()