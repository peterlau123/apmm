#!/usr/bin/env python3
"""
诊断空 patch 问题 - 在 vLLM 服务节点运行
用法: python diagnose_empty_patch.py
"""

import json
import openai
from pathlib import Path

# 测试空 patch 实例（从 predictions.jsonl 中选取实际空的实例）
TEST_INSTANCES = [
    # ponylang/ponyc (空patch率 79.3%)
    ("c/ponylang__ponyc_dataset.jsonl", 651),
    ("c/ponylang__ponyc_dataset.jsonl", 728),
    # jqlang/jq (空patch率 88.2%)
    ("c/jqlang__jq_dataset.jsonl", 1160),
    # ripgrep (空patch实例)
    ("rust/BurntSushi__ripgrep_dataset.jsonl", 454),
    ("rust/BurntSushi__ripgrep_dataset.jsonl", 727),
    # fmtlib/fmt (对比成功实例)
    ("cpp/fmtlib__fmt_dataset.jsonl", 4310),
]

def create_prompt(instance):
    """从 Multi-SWE-bench 数据创建 prompt"""
    prompt_parts = []

    if instance.get("title"):
        prompt_parts.append(f"Title: {instance['title']}")

    # 处理可能为 None 的 body
    body = instance.get("body")
    if body:
        body = body[:1000] if len(body) > 1000 else body
        prompt_parts.append(f"\nDescription:\n{body}")

    if instance.get("resolved_issues"):
        issues_text = []
        for issue in instance["resolved_issues"][:1]:  # 只取第一个
            issue_text = f"Issue #{issue.get('number')}: {issue.get('title', '')}"
            issue_body = issue.get('body')
            if issue_body:
                issue_text += f"\n{issue_body[:300]}"
            issues_text.append(issue_text)
        prompt_parts.append(f"\nRelated Issue:\n" + "\n".join(issues_text))

    prompt_parts.append("\n\nPlease generate a patch to fix this issue.")
    prompt_parts.append("The patch should be in unified diff format (diff --git a/... b/...).")

    return "\n".join(prompt_parts)


def main():
    dataset_base = Path("/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench")
    output_file = Path("/gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE/diagnose_results.json")

    # 配置 vLLM client
    client = openai.OpenAI(
        api_key="EMPTY",
        base_url="http://localhost:9527/v1"
    )

    results = []

    for dataset_file, number in TEST_INSTANCES:
        dataset_path = dataset_base / dataset_file
        if not dataset_path.exists():
            print(f"Dataset not found: {dataset_path}")
            continue

        # 加载实例
        instance = None
        for line in open(dataset_path):
            d = json.loads(line)
            if d['number'] == number:
                instance = d
                break

        if not instance:
            print(f"Instance #{number} not found in {dataset_file}")
            continue

        org = instance['org']
        repo = instance['repo']
        print(f"\n{'='*60}")
        print(f"Testing: {org}/{repo}#{number}")
        print(f"{'='*60}")

        # 构造 prompt
        prompt = create_prompt(instance)
        print(f"Prompt length: {len(prompt)} chars")
        print(f"Prompt preview:\n{prompt[:200]}...")

        # 调用模型
        try:
            response = client.chat.completions.create(
                model="MiniMax-M2.7",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=4096,
            )
            output = response.choices[0].message.content

            print(f"\nModel output length: {len(output)} chars")
            print(f"Output preview:\n{output[:500]}...")

            # 检查 diff 格式
            has_diff = "diff --git" in output
            has_patch_tag = "<patch>" in output or "<diff>" in output
            has_code_block = "```diff" in output or "```patch" in output

            print(f"\nFormat check:")
            print(f"  - Has 'diff --git': {has_diff}")
            print(f"  - Has <patch>/<diff> tag: {has_patch_tag}")
            print(f"  - Has ```diff/```patch block: {has_code_block}")

            # 保存结果
            result = {
                "org": org,
                "repo": repo,
                "number": number,
                "prompt_length": len(prompt),
                "output_length": len(output),
                "has_diff_format": has_diff,
                "has_patch_tag": has_patch_tag,
                "has_code_block": has_code_block,
                "model_output": output[:2000],  # 保存前2000字符
                "ground_truth_patch": instance.get('fix_patch', '')[:500],
            }
            results.append(result)

        except Exception as e:
            print(f"Error: {e}")
            results.append({
                "org": org,
                "repo": repo,
                "number": number,
                "error": str(e),
            })

    # 保存诊断结果
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Results saved to: {output_file}")
    print(f"{'='*60}")

    # 统计
    success = sum(1 for r in results if r.get('has_diff_format'))
    print(f"\nSummary:")
    print(f"  Total tested: {len(results)}")
    print(f"  Has 'diff --git': {success}")
    print(f"  No diff format: {len(results) - success}")


if __name__ == '__main__':
    main()