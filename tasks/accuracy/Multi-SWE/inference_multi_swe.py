#!/usr/bin/env python3
"""
Multi-SWE-bench 推理脚本：使用 vLLM API 生成 fix_patch

数据格式：
- 输入：title + body + hints（作为 prompt）
- 输出：org/repo/number/fix_patch（JSONL）

评测使用：
python -m multi_swe_bench.harness.run_evaluation --config config.json
"""

import json
import os
import glob
from pathlib import Path
from tqdm import tqdm
import openai
import argparse
import requests


def create_prompt(instance):
    """
    从 Multi-SWE-bench 数据创建 prompt

    Args:
        instance: 数据实例，包含 title/body/hints 等字段
    """
    prompt_parts = []

    # 标题
    if instance.get("title"):
        prompt_parts.append(f"Title: {instance['title']}")

    # 问题描述
    if instance.get("body"):
        prompt_parts.append(f"\nDescription:\n{instance['body']}")

    # 关联 issue
    if instance.get("resolved_issues"):
        issues_text = []
        for issue in instance["resolved_issues"]:
            issue_text = f"Issue #{issue.get('number')}: {issue.get('title', '')}"
            if issue.get("body"):
                issue_text += f"\n{issue['body'][:500]}..."  # 截取前500字符
            issues_text.append(issue_text)
        prompt_parts.append(f"\nRelated Issues:\n" + "\n".join(issues_text))

    # Hints（如果有）
    if instance.get("hints"):
        prompt_parts.append(f"\nHints:\n{instance['hints']}")

    # 指令
    prompt_parts.append("\n\nPlease generate a patch to fix this issue.")
    prompt_parts.append("The patch should be in unified diff format (diff --git a/... b/...).")

    return "\n".join(prompt_parts)


def extract_diff(response):
    """
    从模型响应中提取 diff patch
    """
    if response is None:
        return ""

    # 尝试多种格式提取
    import re

    # 方式1: <patch> 或 <diff> 标签
    pattern = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            return match.strip()

    # 方式2: ```diff 或 ```patch 代码块
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            return match.strip()

    # 方式3: 直接查找 diff --git 开头的内容
    diff_pattern = re.compile(r"(diff --git.*?)(?=diff --git|\Z)", re.DOTALL)
    matches = diff_pattern.findall(response)
    if matches:
        return matches[0].strip()

    # 方式4: 返回整个响应（可能模型直接生成了 patch）
    return response.strip()


def load_dataset(dataset_path):
    """
    加载 Multi-SWE-bench 数据集

    Args:
        dataset_path: 数据集目录路径（包含各语言的 JSONL 文件）
    """
    dataset_path = Path(dataset_path)
    instances = []

    # 查找所有 *_dataset.jsonl 文件
    jsonl_files = []
    if dataset_path.is_file() and dataset_path.suffix == ".jsonl":
        jsonl_files = [dataset_path]
    elif dataset_path.is_dir():
        for lang_dir in dataset_path.iterdir():
            if lang_dir.is_dir() and not lang_dir.name.startswith('.'):
                jsonl_files.extend(lang_dir.glob("*_dataset.jsonl"))

    print(f"Found {len(jsonl_files)} dataset files")

    # 加载所有实例
    for jsonl_file in jsonl_files:
        print(f"Loading {jsonl_file}")
        with open(jsonl_file) as f:
            for line in f:
                if line.strip():
                    instance = json.loads(line)
                    instances.append(instance)

    print(f"Total instances: {len(instances)}")
    return instances


def generate_predictions(
    dataset_path: str,
    output_file: str,
    api_base: str = "http://localhost:8000/v1",
    model_name: str = "MiniMax-M2.7",
    temperature: float = 0.2,
    max_tokens: int = 4096,
    languages: list = None,
    max_instances: int = None,
):
    """
    使用 vLLM API 生成 predictions

    Args:
        dataset_path: Multi-SWE-bench 数据集目录
        output_file: 输出 JSONL 文件路径
        api_base: vLLM API base URL
        model_name: 模型名称
        temperature: 生成温度
        max_tokens: 最大生成 token 数
        languages: 只处理特定语言（可选）
        max_instances: 最大处理实例数（可选，用于测试）
    """

    # 配置 OpenAI client
    client = openai.OpenAI(
        api_key="EMPTY",
        base_url=api_base
    )

    # 加载数据集
    instances = load_dataset(dataset_path)

    # 过滤特定语言
    if languages:
        instances = [i for i in instances if any(lang in str(i) for lang in languages)]
        print(f"Filtered to {len(instances)} instances for languages: {languages}")

    # 限制实例数
    if max_instances:
        instances = instances[:max_instances]
        print(f"Processing {max_instances} instances (limited)")

    # 创建输出目录
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 加载已有的 predictions（支持续传）
    existing_ids = set()
    if output_path.exists():
        with open(output_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    key = f"{data['org']}__{data['repo']}-{data['number']}"
                    existing_ids.add(key)
        print(f"Found {len(existing_ids)} existing predictions")

    # 统计
    success_count = 0
    error_count = 0

    # 生成 predictions
    with open(output_path, 'a') as f:
        for instance in tqdm(instances, desc="Generating predictions"):
            org = instance.get("org")
            repo = instance.get("repo")
            number = instance.get("number")

            key = f"{org}__{repo}-{number}"

            # 跳过已处理的
            if key in existing_ids:
                continue

            # 构造 prompt
            prompt = create_prompt(instance)

            # 调用 vLLM API
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # 提取生成内容
                full_output = response.choices[0].message.content

                # 提取 patch
                model_patch = extract_diff(full_output)

                # 保存 prediction（Multi-SWE-bench 格式）
                prediction = {
                    "org": org,
                    "repo": repo,
                    "number": number,
                    "fix_patch": model_patch,
                    # 可选：用于调试
                    # "full_output": full_output[:1000] + "..." if len(full_output) > 1000 else full_output
                }

                f.write(json.dumps(prediction, ensure_ascii=False) + '\n')
                f.flush()
                success_count += 1

            except Exception as e:
                print(f"Error processing {key}: {e}")
                # 保存错误信息
                prediction = {
                    "org": org,
                    "repo": repo,
                    "number": number,
                    "fix_patch": "",
                    "error": str(e)
                }
                f.write(json.dumps(prediction, ensure_ascii=False) + '\n')
                f.flush()
                error_count += 1

    print(f"\n✓ Predictions saved to {output_file}")
    print(f"  Success: {success_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total processed: {success_count + error_count}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset_path",
        type=str,
        default="/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench",
        help="Path to Multi-SWE-bench dataset directory"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=True,
        help="Path to output predictions JSONL file"
    )
    parser.add_argument(
        "--api_base",
        type=str,
        default="http://localhost:8000/v1",
        help="vLLM API base URL"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="MiniMax-M2.7",
        help="Model name (must match --served-model-name in vLLM)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Generation temperature"
    )
    parser.add_argument(
        "--max_tokens",
        type=int,
        default=4096,
        help="Maximum tokens to generate"
    )
    parser.add_argument(
        "--languages",
        type=str,
        nargs="*",
        default=None,
        help="Only process specific languages (e.g., --languages rust cpp)"
    )
    parser.add_argument(
        "--max_instances",
        type=int,
        default=None,
        help="Maximum number of instances to process (for testing)"
    )

    args = parser.parse_args()

    # 检查 vLLM 服务是否运行
    try:
        resp = requests.get(f"{args.api_base}/models", timeout=5)
        print(f"✓ vLLM service is running at {args.api_base}")
        models = resp.json().get("data", [])
        if models:
            print(f"  Available models: {[m['id'] for m in models]}")
    except Exception as e:
        print(f"⚠ Warning: vLLM service not detected at {args.api_base}")
        print(f"  Please ensure vLLM is running:")
        print(f"  vllm serve /path/to/model --host 0.0.0.0 --port 8000 --served-model-name {args.model_name}")

    generate_predictions(
        dataset_path=args.dataset_path,
        output_file=args.output_file,
        api_base=args.api_base,
        model_name=args.model_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        languages=args.languages,
        max_instances=args.max_instances,
    )