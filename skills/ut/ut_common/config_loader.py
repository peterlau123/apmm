"""
配置加载器 - 从 workflow_state.json 或命令行参数读取配置

用途：
- 统一配置管理，消除硬编码路径
- 支持从 workflow_state.json 读取所有路径配置
- 支持命令行参数覆盖
- 支持动态运行目录（{test_name}-{timestamp}）

使用方法：
    from shared.config_loader import get_paths, get_config, create_run_dir

    # 创建运行目录并获取路径
    run_dir = create_run_dir(test_name="ut")
    paths = get_paths()
    manifest_path = paths["manifest"]

    # 或者指定 workflow_state.json 路径
    paths = get_paths("/custom/path/workflow_state.json")
"""

import json
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# 默认 workflow.yaml 和 workflow_state.json 路径（相对于技能目录）
SKILL_DIR = Path(__file__).parent.parent
DEFAULT_WORKFLOW_YAML = SKILL_DIR.parent.parent / ".agents" / "workflow.yaml"
DEFAULT_WORKFLOW_STATE = SKILL_DIR.parent.parent / ".agents" / "workflow_state.json"
DEFAULT_RUNS_DIR = SKILL_DIR.parent.parent / "runs"


def load_workflow_yaml(workflow_yaml_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    加载 workflow.yaml

    Args:
        workflow_yaml_path: 可选的 workflow.yaml 路径

    Returns:
        dict: workflow.yaml 内容
    """
    if workflow_yaml_path is None:
        workflow_yaml_path = DEFAULT_WORKFLOW_YAML

    if not isinstance(workflow_yaml_path, Path):
        workflow_yaml_path = Path(workflow_yaml_path)

    if workflow_yaml_path.exists():
        try:
            return yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def create_run_dir(
    test_name: Optional[str] = None,
    workspace: Optional[Path] = None,
    workflow_yaml_path: Optional[Path] = None
) -> Path:
    """
    创建运行目录

    目录格式: {workspace}/runs/{test_name}-{timestamp}
    示例: D:/workspace/apmm/runs/ut-20260610-120000

    Args:
        test_name: 测试名称，如未提供则从 workflow.yaml 读取
        workspace: 工作空间目录，如未提供则从 workflow.yaml 读取
        workflow_yaml_path: workflow.yaml 路径

    Returns:
        Path: 创建的运行目录路径
    """
    # 从 workflow.yaml 读取配置
    config = load_workflow_yaml(workflow_yaml_path)

    if test_name is None:
        test_name = config.get("workflow", {}).get("test_name", "ut")

    if workspace is None:
        workspace_str = config.get("config", {}).get("workspace", str(DEFAULT_RUNS_DIR.parent))
        workspace = Path(workspace_str)

    # 确定 runs_dir
    runs_dir_str = config.get("config", {}).get("runs_dir", str(workspace / "runs"))
    runs_dir = Path(runs_dir_str)

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 创建运行目录
    run_dir = runs_dir / f"{test_name}-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    return run_dir


def load_workflow_state(workflow_state_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    加载 workflow_state.json

    Args:
        workflow_state_path: 可选的 workflow_state.json 路径
                              如果未提供，尝试从 current_run.json 或默认路径加载

    Returns:
        dict: workflow_state 内容，如果文件不存在返回空字典
    """
    if workflow_state_path is None:
        # 尝试从 current_run.json 获取路径
        current_run = get_current_run()
        if current_run and current_run.get("workflow_state_path"):
            workflow_state_path = Path(current_run["workflow_state_path"])
        else:
            workflow_state_path = DEFAULT_WORKFLOW_STATE

    if not isinstance(workflow_state_path, Path):
        workflow_state_path = Path(workflow_state_path)

    if workflow_state_path.exists():
        try:
            return json.loads(workflow_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {}
    return {}


def get_current_run() -> Optional[Dict[str, Any]]:
    """
    读取 current_run.json 指针文件，获取当前活跃的运行目录信息

    Returns:
        dict: current_run.json 内容，包含 run_dir, workflow_state_path 等
              如果文件不存在或无效，返回 None
    """
    current_run_path = SKILL_DIR.parent.parent / ".agents" / "current_run.json"

    if current_run_path.exists():
        try:
            data = json.loads(current_run_path.read_text(encoding="utf-8"))
            # 验证必要字段
            if data.get("run_dir") and data.get("workflow_state_path"):
                return data
        except (json.JSONDecodeError, Exception):
            pass

    return None


def get_current_run_dir() -> Optional[Path]:
    """
    获取当前活跃的运行目录路径

    Returns:
        Path: 运行目录路径，如果不存在返回 None
    """
    current_run = get_current_run()
    if current_run and current_run.get("run_dir"):
        return Path(current_run["run_dir"])
    return None


def get_paths(workflow_state_path: Optional[Path] = None) -> Dict[str, Path]:
    """
    获取所有路径配置

    Args:
        workflow_state_path: 可选的 workflow_state.json 路径

    Returns:
        dict: 路径配置字典，包含以下键：
            - workflow_state: workflow_state.json 路径
            - manifest: manifest.json 路径
            - batch_config: batch_config.json 路径
            - batch_results: batch_results.json 路径
            - handled_tests: handled_tests.json 路径
            - run_dir: 运行目录（动态生成）
            - logs_dir: 日志目录
            - reports_dir: 报告目录
            - workspace: 工作空间目录
    """
    state = load_workflow_state(workflow_state_path)
    paths_config = state.get("paths", {})

    # 确定运行目录（优先从 workflow_state.json 读取，否则使用默认）
    if workflow_state_path:
        run_dir = Path(workflow_state_path).parent
    else:
        # 尝试从 workflow_state.json 的 paths.run_dir 读取
        run_dir_str = paths_config.get("run_dir")
        if run_dir_str:
            run_dir = Path(run_dir_str)
        else:
            # 回退到旧的 .agents 目录
            run_dir = DEFAULT_WORKFLOW_STATE.parent

    # 工作空间目录
    workspace = run_dir.parent.parent if run_dir.name.startswith("ut-") else run_dir.parent

    return {
        "workflow_state": Path(paths_config.get("workflow_state", str(run_dir / "workflow_state.json"))),
        "manifest": Path(paths_config.get("manifest", str(run_dir / "manifest.json"))),
        "batch_config": Path(paths_config.get("batch_config", str(run_dir / "batch_config.json"))),
        "batch_results": Path(paths_config.get("batch_results", str(run_dir / "batch_results.json"))),
        "handled_tests": Path(paths_config.get("handled_tests", str(run_dir / "handled_tests.json"))),
        "run_dir": run_dir,
        "logs_dir": Path(paths_config.get("logs_dir", str(run_dir / "logs"))),
        "reports_dir": Path(paths_config.get("reports_dir", str(run_dir / "reports"))),
        "test_load": Path(paths_config.get("test_load", "")),
        "workspace": workspace,
    }


def get_config(workflow_state_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    获取完整配置（路径 + 运行时配置）
    
    Returns:
        dict: 完整配置，包含 paths, workflow, stats 等
    """
    state = load_workflow_state(workflow_state_path)
    paths = get_paths(workflow_state_path)
    
    return {
        "paths": paths,
        "workflow": state.get("workflow", {}),
        "stats": state.get("stats", {}),
        "current_stage": state.get("current_stage", "init"),
        "iteration": state.get("iteration", 0),
        "flags": state.get("flags", {}),
        "remote": state.get("remote", {
            "server": "t_h20",
            "docker": "v0.13.0_torch2.5.1_compile",
            "vllm_dir": "/gpfs/gcsp/M2.7_verify/vllm"
        })
    }


def resolve_path(path_str: str, workflow_state_path: Optional[Path] = None) -> Path:
    """
    解析路径字符串，支持占位符替换

    Args:
        path_str: 可能包含占位符的路径字符串
                  例如: "{run_dir}/manifest.json", "{workspace}/..."
        workflow_state_path: workflow_state.json 路径

    Returns:
        Path: 解析后的绝对路径
    """
    paths = get_paths(workflow_state_path)

    # 替换占位符（按优先级）
    result = path_str
    result = result.replace("{run_dir}", str(paths["run_dir"]))
    result = result.replace("{workspace}", str(paths["workspace"]))
    result = result.replace("{logs_dir}", str(paths["logs_dir"]))
    result = result.replace("{reports_dir}", str(paths["reports_dir"]))
    result = result.replace("{manifest_path}", str(paths["manifest"]))
    result = result.replace("{batches_dir}", str(paths["run_dir"] / "batches"))

    return Path(result)


def resolve_batch_path(
    path_str: str,
    batch_id: str,
    workflow_state_path: Optional[Path] = None
) -> Path:
    """
    解析批次相关路径字符串，支持 {batch_id} 占位符

    Args:
        path_str: 可能包含占位符的路径字符串
                  例如: "{run_dir}/batches/{batch_id}/batch_config.json"
        batch_id: 批次ID，如 "batch_20260610_120000"
        workflow_state_path: workflow_state.json 路径

    Returns:
        Path: 解析后的绝对路径
    """
    # 先解析基础占位符
    result = resolve_path(path_str, workflow_state_path)

    # 再替换 {batch_id}
    result_str = str(result).replace("{batch_id}", batch_id)

    return Path(result_str)


def create_batch_dir(
    batch_id: str,
    workflow_state_path: Optional[Path] = None
) -> Path:
    """
    创建批次目录

    Args:
        batch_id: 批次ID
        workflow_state_path: workflow_state.json 路径

    Returns:
        Path: 创建的批次目录路径
    """
    paths = get_paths(workflow_state_path)
    batch_dir = paths["run_dir"] / "batches" / batch_id

    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "logs").mkdir(exist_ok=True)

    return batch_dir


def add_workflow_state_arg(parser: argparse.ArgumentParser) -> None:
    """
    为 argparse 添加 --workflow-state 参数

    使用示例:
        parser = argparse.ArgumentParser()
        add_workflow_state_arg(parser)
        args = parser.parse_args()
        paths = get_paths(args.workflow_state)
    """
    parser.add_argument(
        "--workflow-state",
        type=str,
        default=None,
        help="workflow_state.json 路径（可选，默认使用 runs/{test_name}-{timestamp}/ 目录）"
    )


def get_paths_from_args(args: argparse.Namespace) -> Dict[str, Path]:
    """
    从 argparse 参数获取路径配置
    
    Args:
        args: argparse.parse_args() 返回的对象
    
    Returns:
        dict: 路径配置字典
    """
    workflow_state_path = getattr(args, "workflow_state", None)
    if workflow_state_path:
        return get_paths(Path(workflow_state_path))
    return get_paths()


if __name__ == "__main__":
    # 测试
    import sys
    print("=== 配置加载器测试 ===")
    print(f"默认 workflow_state.json 路径: {DEFAULT_WORKFLOW_STATE}")
    
    state = load_workflow_state()
    if state:
        print(f"[OK] 加载成功")
        print(f"  workflow: {state.get('workflow', {}).get('name', 'N/A')}")
        print(f"  current_stage: {state.get('current_stage', 'N/A')}")
    else:
        print("[INFO] workflow_state.json 不存在或为空")
    
    paths = get_paths()
    print("\n=== 路径配置 ===")
    for name, path in paths.items():
        exists = "✓" if path.exists() else "✗"
        print(f"  {name}: {path} [{exists}]")