"""run 环境完整性验证: workflow.yaml/container_env 配置 (2026-08-08 HF hang 根因修复).

背景: 新 run 缺 workflow.yaml → execute_batch 读不到 container_env
(HF_HOME/HF_HUB_OFFLINE) → 测试离线 HF 下载 hang → 占满并发 → 假活.
本测试验证修复后的环境完整性 (单元级 + execute_batch 解析级).
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parents[3]
RUN_DIR = PROJECT_ROOT / "runs/ut-20260808-manifest-remaining"

# 必须存在的关键环境变量 (缺失会导致 HF 下载 hang)
REQUIRED_ENV = ("HF_HOME", "HF_HUB_OFFLINE", "HF_HUB_CACHE", "TRANSFORMERS_CACHE")


def test_workflow_yaml_exists():
    """新 run 必须有 workflow.yaml (execute_batch 读 container_env 的源)."""
    assert (RUN_DIR / "workflow.yaml").is_file(), "缺 workflow.yaml → container_env 空 → HF hang"


def test_container_env_has_hf_offline():
    """container_env 必须含 HF 离线关键变量."""
    wf = yaml.safe_load((RUN_DIR / "workflow.yaml").read_text(encoding="utf-8"))
    ce = wf.get("config", {}).get("container_env", {})
    for k in REQUIRED_ENV:
        assert k in ce, f"container_env 缺 {k}"
    assert ce.get("HF_HUB_OFFLINE") == "1", "HF_HUB_OFFLINE 必须为 1 (离线快速失败而非 hang)"


def test_workflow_state_paths_points_to_yaml():
    """workflow_state.paths.workflow_yaml 必须指向存在的工作流文件."""
    ws = json.loads((RUN_DIR / "workflow_state.json").read_text(encoding="utf-8"))
    yaml_str = ws.get("paths", {}).get("workflow_yaml", "")
    assert yaml_str, "workflow_state 缺 paths.workflow_yaml → execute_batch 找不到 container_env"
    p = Path(yaml_str.replace("\\", "/"))
    if not p.is_absolute():
        p = PROJECT_ROOT / p if p.parts and p.parts[0] == "runs" else RUN_DIR / p
    assert p.is_file(), f"workflow_yaml 路径不存在: {p}"


def test_rerun_script_env_has_hf():
    """rerun 脚本 ENV 必须含 HF 离线变量 (execute_batch 进程 env 兜底)."""
    src = (PROJECT_ROOT / "tasks/ut/scripts/rerun_selective.py").read_text(encoding="utf-8")
    assert "HF_HUB_OFFLINE" in src and 'HF_HUB_OFFLINE": "1"' in src, "rerun ENV 缺 HF_HUB_OFFLINE"
    assert "HF_HOME" in src, "rerun ENV 缺 HF_HOME"


def test_execute_batch_resolves_container_env():
    """execute_batch 解析路径 (workflow_state.paths.workflow_yaml → container_env) 纯逻辑验证.

    与 execute_batch.py L870-890 同规则: paths.workflow_yaml 归一化 + 锚定,
    runs/ 前缀 → 项目根; 再读 config.container_env (排除 CUDA_VISIBLE_DEVICES).
    """
    ws = json.loads((RUN_DIR / "workflow_state.json").read_text(encoding="utf-8"))
    yaml_str = ws["paths"]["workflow_yaml"].replace("\\", "/")
    if not Path(yaml_str).is_absolute():
        if Path(yaml_str).parts and Path(yaml_str).parts[0] == "runs":
            yaml_path = PROJECT_ROOT / yaml_str
        else:
            yaml_path = RUN_DIR / yaml_str
    else:
        yaml_path = Path(yaml_str)
    assert yaml_path.is_file(), f"execute_batch 解析出的 workflow_yaml 不存在: {yaml_path}"
    wf = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    ce = {k: v for k, v in wf.get("config", {}).get("container_env", {}).items()
          if k != "CUDA_VISIBLE_DEVICES"}
    assert ce.get("HF_HUB_OFFLINE") == "1"
    assert ce.get("HF_HOME", "").startswith("/gpfs/")
