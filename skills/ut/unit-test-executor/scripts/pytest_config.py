"""
pytest参数配置
用于统一管理所有测试执行的pytest参数

过滤规则已迁移至 skills/ut/shared/filter_rules.yaml
使用 load_filter_rules.py 获取排除规则
"""

from shared.load_filter_rules import get_exclude_patterns

# pytest参数配置（精简版）
PYTEST_ARGS = {
    # 基础参数
    "verbosity": "-q",  # quiet模式，适合批量测试

    # 回溯参数
    "tb_style": "--tb=long",  # 详细回溯，便于问题分类

    # 其他参数
    "extra_args": [
        "-x",  # 首次失败停止（可选）
        "--durations=10",  # 显示最慢的10个测试
    ],
}

def get_pytest_cmd(test_node, log_file, timeout=120, extra_args=None):
    """
    构造pytest命令
    
    Args:
        test_node: 测试节点（文件或用例）
        log_file: 日志文件路径
        timeout: 超时时间（秒）
        extra_args: 额外参数列表
    
    Returns:
        str: 完整pytest命令
    """
    # 基础参数
    args = [PYTEST_ARGS["verbosity"], PYTEST_ARGS["tb_style"]]
    
    # 额外参数
    if extra_args:
        args.extend(extra_args)
    else:
        args.extend(PYTEST_ARGS["extra_args"])
    
    # 过滤参数（只在运行整个目录时使用）
    # 单个测试文件不需要ignore
    
    # 构造命令
    cmd = f"timeout {timeout} pytest '{test_node}' {' '.join(args)} 2>&1 | tee {log_file}"
    
    return cmd

def get_pytest_args_string():
    """获取pytest参数字符串"""
    args = [PYTEST_ARGS["verbosity"], PYTEST_ARGS["tb_style"]]
    args.extend(PYTEST_ARGS["extra_args"])
    return " ".join(args)


def get_pytest_ignore_args():
    """获取pytest排除参数字符串（用于运行整个目录时）

    Returns:
        str: 排除参数字符串，如 "--ignore-glob=tests/**/*rocm* --ignore-glob=tests/tpu/* ..."
    """
    exclude_patterns = get_exclude_patterns()
    return " ".join(exclude_patterns)


if __name__ == "__main__":
    # 测试
    print("Pytest args:", get_pytest_args_string())
    print("Pytest ignore args:", get_pytest_ignore_args()[:100] + "...")
    print("Example command:")
    print(get_pytest_cmd("tests/test_config.py", "test.log", 120))