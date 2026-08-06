#!/usr/bin/env python3
"""HF 模型缓存预检：扫描 test_load，提取测试引用的模型清单，供远端缓存核对。

背景：incident 2026-07-19-hf-model-cache-missing -- Phase 1 有 16 个 failed 因
HF 模型未离线缓存（HF_HUB_OFFLINE=1 下无快照）。经验沉淀 #1 要求建立"测试引用
模型清单 -> 缓存预置检查"预检流程。本脚本完成"提取引用清单"这一步。

注意：模型名嵌在 pytest 参数化 test_node 的 [...] 里，用 - 分隔，与参数片段存在
命名歧义（如 TinyLlama/TinyLlama-1.1B-Chat-v1.0 的 name 含 -）。本脚本用启发式
正则提取候选，**输出为候选清单，需人工核对**。远端 ls HF 缓存目录才是准确的已缓存
清单（见输出末尾的核对命令）。

用法：
    python check_hf_cache_refs.py --test-load runs/ut-XXX/test_load_*.json
    python check_hf_cache_refs.py --test-load ... --remote   # 同时打印远端核对命令
"""
import argparse
import json
import re
import sys
from pathlib import Path

# org 前必须是参数分隔符 [- 或 [，避免把前一个参数片段粘进 org
# org 允许字母/数字/_/-（如 meta-llama, deepseek-ai, Alibaba-NLP）
# name 允许字母/数字/_/./-，非贪婪到参数边界
_PARAM_BOUNDARY = (
    r"(?=-parallel_setup|-test_options|-AttentionBackend|-FLASH_ATTN|"
    r"-model_kwargs|-matches|-rms_norm|-uni\b|-backed|-unbacked|"
    r"-size_oblivious|-mp\b|-ray\b|-auto\b|-True\b|-False\b|-\d|\])"
)
_MODEL_RE = re.compile(
    r"(?<=[\[-])([A-Za-z][A-Za-z0-9_-]*/[A-Za-z][A-Za-z0-9_.-]*?)" + _PARAM_BOUNDARY
)

# org 看起来像参数片段而非 HF org 的，过滤掉
_PARAM_ORGS = {
    "True", "False", "mp", "ray", "auto", "uni", "backed", "unbacked",
    "size_oblivious", "FLASH_ATTN", "TRITON_ATTN", "FLASHINFER",
    "compilation_config", "esb-datasets-earnings22-validation-tiny-filtered",
}


def extract_model_refs(test_load: dict) -> list:
    """从 test_load 的 test_node 提取候选模型引用（可能不精确，需核对）。"""
    models = set()
    for t in test_load.get("tests", []):
        node = t.get("test_node", "")
        for m in _MODEL_RE.findall(node):
            # org 段里若含参数词/纯数字，说明前面粘了参数片段，丢弃
            org = m.split("/", 1)[0]
            org_parts = org.split("-")
            if any(
                p in _PARAM_ORGS or p.isdigit()
                or p.startswith("compilation_config") or p == "datasets"
                for p in org_parts
            ):
                continue
            models.add(m)
    return sorted(models)


def main():
    ap = argparse.ArgumentParser(description="HF 模型缓存预检：提取 test_load 引用模型清单")
    ap.add_argument("--test-load", required=True, help="test_load.json 路径")
    ap.add_argument("--remote", action="store_true", help="打印远端 HF 缓存核对命令")
    args = ap.parse_args()

    p = Path(args.test_load)
    if not p.exists():
        print(json.dumps({"error": f"test_load not found: {p}"}))
        sys.exit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    tests = data.get("tests", [])
    models = extract_model_refs(data)

    print(f"[HF 缓存预检] test_load: {p}")
    print(f"[HF 缓存预检] 测试总数: {len(tests)}")
    print(f"[HF 缓存预检] 候选模型引用: {len(models)} 个（需人工核对，可能含截断/误判）")
    print("-" * 60)
    for m in models:
        print(f"  {m}")
    print("-" * 60)

    if args.remote:
        # HF 缓存目录结构：models--<org>--<name>/，/ 和 - 都替换为 --
        print("\n[远端核对命令] 在容器内执行，列出已缓存模型：")
        print("  ls ~/.cache/huggingface/hub/ | grep '^models--' "
              "|| ls $HF_HOME/hub/ | grep '^models--'")
        print("\n[对照] 把上面候选清单与远端 ls 结果对照，缺失的需预下载：")
        print("  HF_ENDPOINT=https://hf-mirror.com huggingface-cli download <org/name>")
        print("  # 需授权模型用 modelscope：modelscope download --model <repo>")


if __name__ == "__main__":
    main()
