"""
共享模块

提供统一的工具函数：
- path_setup: 自动设置项目路径（导入时自动执行）
- config_loader: 配置加载
- load_filter_rules: 过滤规则
- validate_schema: Schema 校验
"""

# 首先设置路径（确保 skills 包可被导入）
from .path_setup import setup_path
setup_path()

from .config_loader import (
    load_workflow_yaml,
    create_run_dir,
    load_workflow_state,
    get_current_run,
    get_current_run_dir,
    get_paths,
    get_config,
    resolve_path,
    resolve_batch_path,
    create_batch_dir,
    add_workflow_state_arg,
    get_paths_from_args,
)

from .load_filter_rules import (
    get_exclude_patterns,
    get_distributed_patterns,
    is_distributed,
    filter_test_list,
    get_rules_metadata,
)

from .validate_schema import (
    validate_json,
    validate_yaml,
    validate_and_write,
)

__all__ = [
    # path_setup
    "setup_path",
    # config_loader
    "load_workflow_yaml",
    "create_run_dir",
    "load_workflow_state",
    "get_current_run",
    "get_current_run_dir",
    "get_paths",
    "get_config",
    "resolve_path",
    "resolve_batch_path",
    "create_batch_dir",
    "add_workflow_state_arg",
    "get_paths_from_args",
    # load_filter_rules
    "get_exclude_patterns",
    "get_distributed_patterns",
    "is_distributed",
    "filter_test_list",
    "get_rules_metadata",
    # validate_schema
    "validate_json",
    "validate_yaml",
    "validate_and_write",
]