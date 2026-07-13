#!/usr/bin/env python3
"""
init_workflow_state.py - 初始化 workflow_state.json

用途：
- Supervisor启动时调用，初始化状态文件
- 创建动态运行目录 {runs_dir}/{test_name}-{timestamp}
- 创建批次目录结构 batches/
- 拷贝 test_list.txt 到运行目录
- 提供状态文件的标准结构
- 支持从workflow.yaml读取配置
- 创建 current_run.json 指针文件

用法：
    python init_workflow_state.py --test-list PATH
    python init_workflow_state.py --workflow-yaml PATH --test-list PATH
    python init_workflow_state.py --run-dir PATH  # 使用已有运行目录
    python init_workflow_state.py --reset
"""

import argparse
import json
import shutil
import sys

from datetime import datetime, timezone
from pathlib import Path

# 先设置路径（确保 skills 包可被导入）
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import yaml

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from skills.ut.shared import create_run_dir, load_workflow_yaml
from skills.ut.shared import validate_and_write


def copy_test_list(test_list_source: Path, run_dir: Path) -> Path:
    """
    拷贝 test_list.txt 到运行目录

    Args:
        test_list_source: 用户指定的 test_list.txt 原始路径
        run_dir: 运行目录路径

    Returns:
        Path: 拷贝后的文件路径
    """
    if test_list_source and test_list_source.exists():
        dest_path = run_dir / "test_list.txt"
        shutil.copy2(test_list_source, dest_path)
        print(f"[INFO] test_list.txt 已拷贝: {test_list_source} -> {dest_path}")
        return dest_path
    else:
        print(f"[WARN] test_list.txt 源文件不存在或未指定: {test_list_source}")
        return None


def get_initial_pending_count(manifest_path: Path) -> int:
    """从manifest.json读取初始pending_count"""
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tests = manifest.get("tests", [])
        pending = [t for t in tests if t.get("status") == "pending"]
        return len(pending)
    return 0


def get_initial_total_count(manifest_path: Path) -> int:
    """从manifest.json读取总测试数"""
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return len(manifest.get("tests", []))
    return 0


def create_manifest_from_test_list(test_list_path: Path, manifest_path: Path) -> int:
    """从 test_list.txt 创建 manifest.json"""
    if not test_list_path.exists():
        return 0

    lines = [
        l.strip()
        for l in test_list_path.read_text(encoding='utf-8').splitlines()
        if l.strip() and not l.startswith("#")
    ]

    tests = []
    for i, node in enumerate(lines, 1):
        # 解析 test_node: tests/xxx.py::test_name
        parts = node.split("::")
        test_file = parts[0] if len(parts) >= 1 else node
        test_name = parts[1] if len(parts) >= 2 else ""
        tests.append(
            {
                "id": i,
                "test_node": node,
                "test_file": test_file,
                "test_name": test_name,
                "status": "pending",
            }
        )

    manifest = {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "test_list_file",
        "tests": tests,
        "statistics": {"total": len(tests), "pending": len(tests)},
    }

    validate_and_write(manifest, "manifest", manifest_path)
    return len(tests)


def update_current_run_pointer(
    agents_dir: Path,
    run_dir: Path,
    workflow_state_path: Path,
    test_list_path: Path = None,
    status: str = "active",
) -> None:
    """
    更新 current_run.json 指针文件

    Args:
        agents_dir: .agents 目录路径
        run_dir: 运行目录路径
        workflow_state_path: workflow_state.json 路径
        test_list_path: test_list.txt 路径（可选）
        status: 运行状态 (active/completed/paused)
    """
    pointer_file = agents_dir / "current_run.json"
    pointer_data = {
        "run_dir": str(run_dir),
        "workflow_state_path": str(workflow_state_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }

    if test_list_path:
        pointer_data["test_list_path"] = str(test_list_path)

    agents_dir.mkdir(parents=True, exist_ok=True)
    pointer_file.write_text(
        json.dumps(pointer_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[INFO] current_run.json 指针已更新: {pointer_file}")


def create_initial_state(
    workflow_yaml_path: Path,
    run_dir: Path = None,
    manifest_path: Path = None,
    test_list_source: Path = None,
    reset: bool = False,
    template_path: Path = None,
) -> dict:
    """
    创建初始 workflow_state.json

    Args:
        workflow_yaml_path: workflow.yaml 路径
        run_dir: 运行目录路径（可选，如果不指定则自动创建）
        manifest_path: manifest.json 路径（可选，默认在 run_dir 下）
        test_list_source: test_list.txt 原始路径（可选，优先级高于 workflow.yaml 配置）
        reset: 是否重置状态
        template_path: workflow template路径（可选，如果提供则拷贝到run_dir/workflow.yaml）

    Returns:
        dict: 创建的状态数据
    """
    # 加载 workflow.yaml 配置
    config = load_workflow_yaml(workflow_yaml_path)
    workflow_name = config.get("workflow", {}).get("name", "UT Test Workflow")
    workflow_version = config.get("workflow", {}).get("version", "2.0")
    test_name = config.get("workflow", {}).get("test_name", "ut")

    # current_run.json must live at the canonical PROJECT_ROOT/.agents (where
    # ut_runner.init_or_resume reads it). Do NOT derive from the yaml's
    # parent — frozen test configs live outside .agents and would otherwise
    # write the pointer next to the yaml, leaving the canonical one stale.
    agents_dir = _project_root / ".agents"

    # 创建或使用运行目录
    if run_dir is None:
        run_dir = create_run_dir(
            test_name=test_name, workflow_yaml_path=workflow_yaml_path
        )
    else:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        # 创建子目录
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "reports").mkdir(exist_ok=True)

    # 创建批次目录根
    batches_dir = run_dir / "batches"
    batches_dir.mkdir(exist_ok=True)
    print(f"[INFO] 批次目录已创建: {batches_dir}")

    # 拷贝 workflow template（如果指定）
    if template_path and Path(template_path).exists():
        template_source = Path(template_path)
        target_workflow_yaml = run_dir / "workflow.yaml"
        shutil.copy2(template_source, target_workflow_yaml)
        print(f"[OK] Template copied: {template_source} -> {target_workflow_yaml}")
        # 更新 workflow_yaml_path 为拷贝后的路径
        workflow_yaml_path = target_workflow_yaml

    # 确定 test_list_source：优先使用命令行参数，否则从 workflow.yaml 读取
    if test_list_source is None:
        # 从 workflow.yaml 的 input_filter.test_list_path 读取
        input_filter = config.get("input_filter", {})
        test_list_from_yaml = input_filter.get("test_list_path")
        if test_list_from_yaml:
            test_list_source = Path(test_list_from_yaml)
            print(f"[INFO] 从 workflow.yaml 读取 test_list 路径: {test_list_source}")

    # 拷贝 test_list.txt（如果指定）
    test_list_path = None
    if test_list_source:
        test_list_path = copy_test_list(Path(test_list_source), run_dir)

    # 确定各文件路径
    workflow_state_path = run_dir / "workflow_state.json"

    if manifest_path is None:
        manifest_path = run_dir / "manifest.json"

    # 读取 input_filter.manifest_source（优先级高于 test_list_path）
    input_filter = config.get("input_filter", {})
    manifest_source = input_filter.get("manifest_source")

    # 检查是否已存在
    if workflow_state_path.exists() and not reset:
        print(f"[INFO] workflow_state.json 已存在，跳过初始化")
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        update_current_run_pointer(
            agents_dir, run_dir, workflow_state_path, test_list_path
        )
        return state

    now = datetime.now(timezone.utc).isoformat()

    # 创建 manifest.json：
    # 1. manifest_source 指定 -> 拷贝到 run_dir/manifest.json（优先）
    # 2. test_list_path 指定 -> 从 test_list.txt 创建
    # 3. manifest_path 已存在 -> 直接使用
    if manifest_source and Path(manifest_source).exists():
        shutil.copy2(Path(manifest_source), manifest_path)
        print(f"[INFO] manifest.json 已从 manifest_source 拷贝: {manifest_source} -> {manifest_path}")
        pending_count = get_initial_pending_count(manifest_path)
        total_count = get_initial_total_count(manifest_path)
    elif not manifest_path.exists() and test_list_path:
        total_count = create_manifest_from_test_list(test_list_path, manifest_path)
        pending_count = total_count
    else:
        pending_count = get_initial_pending_count(manifest_path)
        total_count = get_initial_total_count(manifest_path)

    # 构建状态数据
    state = {
        "workflow": {
            "name": workflow_name,
            "version": workflow_version,
            "test_name": test_name,
            "started_at": now,
            # v5 schema dropped 'initialized'; a freshly-built run is 'running'
            # (the channel loop drives it immediately). See workflow_state_schema.json.
            "status": "running",
        },
        "current_stage": "collect",
        "iteration": 0,
        "paths": {
            "run_dir": str(run_dir),
            "workflow_yaml": str(workflow_yaml_path),
            "manifest": str(manifest_path),
            "test_list": str(test_list_path) if test_list_path else None,
            "manifest_schema": str(SKILL_DIR / "shared" / "manifest_schema.json"),
            "batches_dir": str(batches_dir),
            "logs_dir": str(run_dir / "logs"),
            "reports_dir": str(run_dir / "reports"),
            "workflow_state": str(workflow_state_path),
        },
        "stats": {
            "total_tests": total_count,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "ignored": 0,
            "pending": pending_count,
            "error_rate": 0.0,
        },
        "current_batch": {"batch_id": None, "size": 0, "started_at": None},
        "flags": {
            "stop_requested": False,
            "pause_requested": False,
            "pause_reason": None,
            "consecutive_failures": 0,
        },
        "last_update": now,
        "last_worker_result": {
            "stats": {"passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 0},
            "next_action": "continue",
            "error": None,
            "blocked_reason": None,
        },
    }

    # 校验后写入 workflow_state.json
    is_valid, errors = validate_and_write(state, "workflow_state", workflow_state_path)
    if not is_valid:
        return {"error": "schema_validation_failed", "details": errors}

    # 更新 current_run.json 指针
    update_current_run_pointer(agents_dir, run_dir, workflow_state_path, test_list_path)

    print(f"[INFO] workflow_state.json 初始化完成")
    print(f"  - run_dir: {run_dir}")
    print(f"  - batches_dir: {batches_dir}")
    print(f"  - test_list: {test_list_path}")
    print(f"  - workflow_yaml: {workflow_yaml_path}")
    print(f"  - manifest: {manifest_path}")
    print(f"  - total_tests: {total_count}")
    print(f"  - pending: {pending_count}")
    print(f"  - workflow_state: {workflow_state_path}")

    return state


def reset_state(
    workflow_yaml_path: Path,
    run_dir: Path = None,
    manifest_path: Path = None,
    test_list_source: Path = None,
    template_path: Path = None,
) -> dict:
    """重置状态文件"""
    print("[INFO] 重置 workflow_state.json...")
    return create_initial_state(
        workflow_yaml_path, run_dir, manifest_path, test_list_source, reset=True, template_path=template_path
    )


def main():
    parser = argparse.ArgumentParser(
        description="初始化 workflow_state.json 并创建动态运行目录"
    )
    parser.add_argument(
        "--workflow-yaml",
        type=str,
        default=str(
            Path(__file__).parent.parent.parent.parent.parent
            / "tasks"
            / "ut"
            / "deployment"
            / "production"
            / "config"
            / "workflow.yaml"
        ),
        help="workflow.yaml 配置文件路径",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="指定运行目录路径（默认：自动创建 {runs_dir}/{test_name}-{timestamp}）",
    )
    parser.add_argument(
        "--manifest-path",
        type=str,
        default=None,
        help="manifest.json 文件路径（默认：run_dir/manifest.json）",
    )
    parser.add_argument(
        "--test-list",
        type=str,
        default=None,
        help="test_list.txt 原始文件路径（将拷贝到运行目录）",
    )
    parser.add_argument("--reset", action="store_true", help="重置状态文件")
    parser.add_argument(
        "--template-path",
        type=str,
        default=None,
        help="Workflow template path (from load_deployment_config). "
             "If provided, copy template to run_dir/workflow.yaml",
    )

    args = parser.parse_args()

    workflow_yaml_path = Path(args.workflow_yaml)
    run_dir = Path(args.run_dir) if args.run_dir else None
    manifest_path = Path(args.manifest_path) if args.manifest_path else None
    test_list_source = Path(args.test_list) if args.test_list else None
    template_path = Path(args.template_path) if args.template_path else None

    result = create_initial_state(
        workflow_yaml_path, run_dir, manifest_path, test_list_source, reset=args.reset, template_path=template_path
    )

    # Fail loudly on a bad init: a validation failure must surface as a non-zero
    # exit so callers (e.g. ut_runner.init_or_resume, which gates on rc != 0)
    # don't silently reuse a stale run_dir with an un-updated current_run.json.
    if isinstance(result, dict) and result.get("error"):
        print(f"[ERROR] init failed: {result['error']}", file=sys.stderr)
        for detail in result.get("details", []):
            print(f"  - {detail}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
