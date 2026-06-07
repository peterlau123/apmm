"""
pytest参数配置
用于统一管理所有测试执行的pytest参数
"""

# pytest参数配置
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
    
    # 过滤参数（排除不支持的平台和模型）
    "ignore_patterns": [
        "--ignore-glob=tests/**/*rocm*",
        "--ignore-glob=tests/tpu/*",
        "--ignore-glob=tests/**/*tpu*",
        "--ignore-glob=tests/**/multimodal*",
        "--ignore-glob=tests/**/nixl*",
        "--ignore-glob=tests/**/ec_connector*",
        "--ignore-glob=tests/**/*image*.py",
        "--ignore-glob=tests/**/*video*.py",
        "--ignore-glob=tests/**/*audio*",
        "--ignore-glob=tests/**/encoder*",
        "--ignore-glob=tests/**/prithvi*",
        "--ignore-glob=tests/models/language/generation/test_gemma.py",
        "--ignore-glob=tests/models/language/generation/test_granite.py",
        "--ignore-glob=tests/models/language/generation/test_hybrid.py",
        "--ignore-glob=tests/models/language/generation/test_mistral.py",
        "--ignore-glob=tests/models/language/generation/test_phimoe.py",
        "--ignore-glob=tests/models/language/generation_ppl_test/test_gemma.py",
        "--ignore-glob=tests/models/language/generation_ppl_test/test_gpt.py",
        "--ignore-glob=tests/models/language/generation_ppl_test/test_qwen.py",
        "--ignore-glob=tests/models/language/pooling_mteb_test/*",
        "--ignore-glob=tests/models/language/pooling/*",
        "--ignore-glob=tests/reasoning/test_deepseekr1_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_deepseekv3_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_ernie45_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_glm4_moe_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_gptoss_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_granite_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_holo2_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_hunyuan_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_mistral_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_olmo3_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_qwen3_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_seedoss_reasoning_parser.py",
        "--ignore-glob=tests/reasoning/test_base_thinking_reasoning_parser.py",
        "--ignore-glob=tests/**/*whisper*",
        "--ignore-glob=tests/**/**multi_modal**",
        "--ignore-glob=tests/**/**_mm_**",
    ]
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

if __name__ == "__main__":
    # 测试
    print("Pytest args:", get_pytest_args_string())
    print("Example command:")
    print(get_pytest_cmd("tests/test_config.py", "test.log", 120))