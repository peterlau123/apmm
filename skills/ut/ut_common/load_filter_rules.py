#!/usr/bin/env python3
"""加载过滤规则模块

从 filter_rules.yaml 加载过滤规则，提供统一接口：
- get_exclude_patterns(): 获取排除规则列表（pytest --ignore-glob 格式）
- get_distributed_patterns(): 获取 distributed 规则列表
- is_distributed(test_node): 检测是否为 distributed 测试
- filter_test_list(tests): 应用排除规则过滤测试列表

用法：
    from shared.load_filter_rules import get_exclude_patterns, is_distributed

    exclude_patterns = get_exclude_patterns()  # ["--ignore-glob=tests/**/*rocm*", ...]
    if is_distributed(test_node):              # True/False
    ...
"""

import yaml
from pathlib import Path
from typing import List, Dict, Any

# 默认路径：skills/ut/ut_common/filter_rules.yaml
DEFAULT_RULES_PATH = Path(__file__).parent / "filter_rules.yaml"

# ── Cache to avoid repeated yaml loading on large manifests ──────────────────
_rules_cache: Dict[str, Dict[str, Any]] = {}


def load_filter_rules(rules_path: Path = None) -> Dict[str, Any]:
    """加载 filter_rules.yaml

    Args:
        rules_path: 规则文件路径（默认使用 DEFAULT_RULES_PATH）

    Returns:
        dict: 规则数据
    """
    if rules_path is None:
        rules_path = DEFAULT_RULES_PATH

    cache_key = str(rules_path)
    if cache_key in _rules_cache:
        return _rules_cache[cache_key]

    if not rules_path.exists():
        raise FileNotFoundError(f"filter_rules.yaml not found: {rules_path}")

    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    _rules_cache[cache_key] = rules
    return rules


def get_exclude_patterns(rules_path: Path = None) -> List[str]:
    """获取排除规则列表（pytest --ignore-glob 格式）

    Returns:
        List[str]: pytest --ignore-glob 参数列表
        例如: ["--ignore-glob=tests/**/*rocm*", "--ignore-glob=tests/tpu/*", ...]
    """
    rules = load_filter_rules(rules_path)
    exclude_patterns = []

    for rule in rules["filter_rules"]["rules"]:
        if rule["type"] == "exclude":
            pattern = rule["pattern"]
            exclude_patterns.append(f"--ignore-glob={pattern}")

    return exclude_patterns


def get_distributed_patterns(rules_path: Path = None) -> List[str]:
    """获取 distributed 规则列表

    Returns:
        List[str]: distributed 模式列表
        例如: ["tests/distributed/", "test_pipeline_parallel", ...]
    """
    rules = load_filter_rules(rules_path)
    distributed_patterns = []

    for rule in rules["filter_rules"]["rules"]:
        if rule["type"] == "distributed":
            distributed_patterns.append(rule["pattern"])

    return distributed_patterns


def is_distributed(test_node: str, rules_path: Path = None) -> bool:
    """检测是否为 distributed 测试

    Args:
        test_node: 测试节点路径（如 "tests/distributed/test_pp.py"）
        rules_path: 规则文件路径

    Returns:
        bool: True 表示 distributed 测试
    """
    distributed_patterns = get_distributed_patterns(rules_path)
    return any(p in test_node for p in distributed_patterns)


def filter_test_list(tests: List[Dict], rules_path: Path = None) -> List[Dict]:
    """应用排除规则过滤测试列表

    Args:
        tests: 测试列表，每个元素包含 test_node 或 test_file 字段
        rules_path: 规则文件路径

    Returns:
        List[Dict]: 过滤后的测试列表
    """
    rules = load_filter_rules(rules_path)
    exclude_patterns = []

    for rule in rules["filter_rules"]["rules"]:
        if rule["type"] == "exclude":
            exclude_patterns.append(rule["pattern"])

    # 转换为 fnmatch 格式（简化匹配）
    import fnmatch

    filtered = []
    for test in tests:
        test_path = test.get("test_node", test.get("test_file", ""))
        # 检查是否匹配任何排除规则
        excluded = False
        for pattern in exclude_patterns:
            # 将 glob 模式转换为 fnmatch
            # tests/**/*rocm* -> tests/*/*rocm* (简化)
            fnmatch_pattern = pattern.replace("**", "*")
            if fnmatch.fnmatch(test_path, fnmatch_pattern) or pattern in test_path:
                excluded = True
                break

        if not excluded:
            filtered.append(test)

    return filtered


def get_rules_metadata(rules_path: Path = None) -> Dict[str, Any]:
    """获取规则元数据

    Returns:
        dict: 包含 updated_at, version, stats
    """
    rules = load_filter_rules(rules_path)
    return {
        "updated_at": rules["filter_rules"]["updated_at"],
        "version": rules["filter_rules"]["version"],
        "stats": rules["filter_rules"]["stats"]
    }


if __name__ == "__main__":
    # 测试
    print("=== Exclude Patterns ===")
    exclude = get_exclude_patterns()
    print(f"Total: {len(exclude)}")
    for p in exclude[:5]:
        print(f"  {p}")
    print("...")

    print("\n=== Distributed Patterns ===")
    distributed = get_distributed_patterns()
    print(f"Total: {len(distributed)}")
    for p in distributed:
        print(f"  {p}")

    print("\n=== is_distributed Test ===")
    test_nodes = [
        "tests/distributed/test_pipeline_parallel.py",
        "tests/test_config.py",
        "tests/models/test_llama.py"
    ]
    for node in test_nodes:
        print(f"  {node}: {is_distributed(node)}")

    print("\n=== Metadata ===")
    metadata = get_rules_metadata()
    print(f"  updated_at: {metadata['updated_at']}")
    print(f"  version: {metadata['version']}")
    print(f"  stats: {metadata['stats']}")