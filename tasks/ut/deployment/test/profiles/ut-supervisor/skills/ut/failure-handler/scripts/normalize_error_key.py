"""
normalize_error_key.py - error_key 标准化脚本（L1 脚本规则）

职责：
- 从原始错误信息提取标准化 error_key
- 遵循脚本优先原则：确定性规则提取
- 不调用 LLM（L5/L6 用于 failure_key）

error_key 格式规则：
- dependency: {package} → transformers
- download_error: {org}/{model} → meta-llama/Llama-3.2-1B
- version: {module}.{function}.{change} → torch.softmax.dim_arg
- network: {host}:{error} → huggingface.co:timeout
- resource: {resource_type} → cuda_oom

用法：
    python normalize_error_key.py --error-type dependency --error-message "ModuleNotFoundError: No module named 'transformers'"
    python normalize_error_key.py --batch-results PATH --output PATH
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime


def normalize_dependency_key(error_message: str) -> str | None:
    """
    dependency: 提取包名

    模式：
    - ModuleNotFoundError: No module named 'transformers'
    - ImportError: cannot import name 'xxx' from 'torch'
    """
    patterns = [
        r"No module named '(\w+)'",
        r"cannot import name.*from '(\w+)'",
        r"ImportError.*(\w+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            return match.group(1).lower()

    return None


def normalize_download_error_key(error_message: str) -> str | None:
    """
    download_error: 提取模型 ID

    模式：
    - Failed to download meta-llama/Llama-3.2-1B
    - Model not found: huggingface.co/meta-llama/Llama-3.2-1B
    """
    patterns = [
        r"download ([\w\-]+/[\w\-\.]+)",
        r"Model not found.*([\w\-]+/[\w\-\.]+)",
        r"([\w\-]+/[\w\-\.]+).*not found",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def normalize_version_key(error_message: str) -> str | None:
    """
    version: 提取 API 变化

    模式：
    - TypeError: softmax() got unexpected keyword argument 'dim'
    - AttributeError: module 'torch' has no attribute 'softmax'
    """
    # 提取 module + function
    module_patterns = [
        r"module '(\w+)'.*?has no attribute '(\w+)'",
        r"(\w+)\.(\w+)\(\).*?unexpected",
    ]

    for pattern in module_patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            module = match.group(1).lower()
            function = match.group(2).lower()

            # 提取变化类型
            change_type = "missing_attr"
            if "unexpected keyword" in error_message.lower():
                change_type = "arg_change"
            elif "unexpected argument" in error_message.lower():
                change_type = "arg_change"

            return f"{module}.{function}.{change_type}"

    # 提取参数变化
    arg_patterns = [
        r"unexpected keyword argument '(\w+)'",
        r"got an unexpected keyword argument '(\w+)'",
    ]

    for pattern in arg_patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            arg = match.group(1).lower()
            # 尝试提取 module.function
            context_match = re.search(r"(\w+)\.(\w+)\(", error_message)
            if context_match:
                return f"{context_match.group(1)}.{context_match.group(2)}.{arg}_arg"
            return f"unknown.{arg}_arg"

    return None


def normalize_network_key(error_message: str) -> str:
    """
    network: 提取 host + error

    模式：
    - timeout: huggingface.co
    - ConnectionError: github.com
    """
    # 提取 host
    host_patterns = [
        r"https?://([\w\.\-]+)",
        r"([\w\.\-]+\.[\w]+)",
    ]

    host = "unknown"
    for pattern in host_patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            host = match.group(1).lower()
            break

    # 提取错误类型
    if "timeout" in error_message.lower():
        return f"{host}:timeout"
    if "connection" in error_message.lower():
        return f"{host}:connection_error"
    if "refused" in error_message.lower():
        return f"{host}:connection_refused"

    return f"{host}:network_unknown"


def normalize_resource_key(error_message: str) -> str:
    """
    resource: 提取资源类型

    模式：
    - CUDA out of memory
    - NCCL error
    - GPU not available
    """
    error_lower = error_message.lower()

    if "cuda out of memory" in error_lower or "oom" in error_lower:
        return "cuda_oom"
    if "nccl" in error_lower:
        return "nccl_error"
    if "gpu" in error_lower and ("not available" in error_lower or "no gpu" in error_lower):
        return "gpu_not_available"

    return "resource_unknown"


def normalize_error_key(error_type: str, error_message: str) -> str | None:
    """
    主入口：根据 error_type 调用对应标准化函数

    Args:
        error_type: 错误类型（dependency/download_error/version/network/resource）
        error_message: 原始错误信息

    Returns:
        标准化 error_key 或 None（无法提取时）
    """
    normalizers = {
        "dependency": normalize_dependency_key,
        "download_error": normalize_download_error_key,
        "version": normalize_version_key,
        "network": normalize_network_key,
        "resource": normalize_resource_key,
    }

    normalizer = normalizers.get(error_type)
    if normalizer:
        return normalizer(error_message)

    return None


def process_batch_results(batch_results_path: Path, output_path: Path = None) -> dict:
    """
    处理 batch_results.json，标准化所有 error_key

    Args:
        batch_results_path: batch_results.json 路径
        output_path: 输出文件路径（可选）

    Returns:
        处理结果 dict
    """
    if not batch_results_path.exists():
        return {"error": f"batch_results.json not found: {batch_results_path}"}

    batch_results = json.loads(batch_results_path.read_text(encoding="utf-8"))

    processed = {
        "batch_id": batch_results.get("batch_id"),
        "processed_at": datetime.now().isoformat(),
        "tests": []
    }

    for test in batch_results.get("tests", []):
        if test.get("status") not in ["failed", "error"]:
            continue

        error_message = test.get("error_message", "")
        error_type = test.get("error_type") or classify_error_type(error_message)

        error_key = normalize_error_key(error_type, error_message)

        processed_test = {
            "test_node": test.get("test_node"),
            "error_type": error_type,
            "error_key": error_key,
            "error_message": error_message[:500],
            "normalized_at": datetime.now().isoformat()
        }

        processed["tests"].append(processed_test)

    # 写入输出
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(processed, indent=2, ensure_ascii=False))
        print(f"[OK] Processed {len(processed['tests'])} tests, saved to: {output_path}")

    return processed


def classify_error_type(error_message: str) -> str:
    """
    简单分类：关键词匹配（用于未分类的测试）
    """
    error_lower = error_message.lower()

    if any(k in error_lower for k in ["modulenotfound", "importerror", "no module named"]):
        return "dependency"
    if any(k in error_lower for k in ["download", "model not found", "failed to download"]):
        return "download_error"
    if any(k in error_lower for k in ["cuda out of memory", "oom", "nccl", "gpu"]):
        return "resource"
    if any(k in error_lower for k in ["timeout", "connection", "refused"]):
        return "network"
    if any(k in error_lower for k in ["typeerror", "attributeerror", "unexpected"]):
        return "version"

    return "other"


def main():
    parser = argparse.ArgumentParser(description="normalize_error_key - error_key 标准化脚本")

    # 单条处理
    parser.add_argument("--error-type", type=str, help="错误类型")
    parser.add_argument("--error-message", type=str, help="错误信息")

    # 批量处理
    parser.add_argument("--batch-results", type=str, help="batch_results.json 路径")
    parser.add_argument("--output", type=str, help="输出文件路径")

    args = parser.parse_args()

    if args.error_type and args.error_message:
        # 单条处理
        error_key = normalize_error_key(args.error_type, args.error_message)
        result = {
            "error_type": args.error_type,
            "error_key": error_key,
            "error_message": args.error_message[:200]
        }
        print(json.dumps(result, indent=2))

    elif args.batch_results:
        # 批量处理
        batch_results_path = Path(args.batch_results)
        output_path = Path(args.output) if args.output else None
        result = process_batch_results(batch_results_path, output_path)

        if "error" not in result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"[ERROR] {result['error']}")

    else:
        # 默认示例
        examples = [
            ("dependency", "ModuleNotFoundError: No module named 'transformers'"),
            ("download_error", "Failed to download meta-llama/Llama-3.2-1B from huggingface.co"),
            ("version", "TypeError: torch.softmax() got unexpected keyword argument 'dim'"),
            ("network", "timeout: https://huggingface.co/api/models"),
            ("resource", "CUDA out of memory. Tried to allocate 2GB"),
        ]

        print("示例输出：")
        for error_type, error_message in examples:
            error_key = normalize_error_key(error_type, error_message)
            print(f"  {error_type}: {error_key}")


if __name__ == "__main__":
    main()