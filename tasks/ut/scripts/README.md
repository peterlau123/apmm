# vLLM 测试模型下载指南

本目录包含从 HuggingFace 和 ModelScope 下载测试所需模型的脚本。

---

## 目录结构

```
ut/
├── hf_hub/              # HuggingFace 缓存（推荐）
├── modelscope/          # ModelScope 缓存（备用）
└── scripts/
    ├── download_models.sh     # 统一下载脚本 ⭐
    ├── hf_env.sh              # HF 离线环境配置
    ├── modelscope_env.sh      # ModelScope 环境配置
    ├── run_filtered_tests.sh  # 运行过滤测试
    └── parse_results.py       # 结果解析
```

---

## 快速使用

### 联网机器下载

```bash
cd ut/scripts/

# 从 HF 镜像下载（推荐，国内快）
./download_models.sh --source hf --level 2   # 小+中等模型 (~10GB)

# 从 ModelScope 下载
./download_models.sh --source ms --level 2

# 全量下载（包含大模型）
./download_models.sh --source hf --all

# 检查缺失
./download_models.sh --check
```

### 离线机器运行测试

```bash
cd ut/scripts/
source hf_env.sh
pytest tests/test_config.py -v -k 'not 72B and not 80B'
```

---

## download_models.sh 使用说明

```bash
./download_models.sh [--source hf|ms] [--level N|--all|--check]
```

| 参数 | 说明 |
|------|------|
| `--source hf` | 使用 HF 镜像（默认，推荐） |
| `--source ms` | 使用 ModelScope |
| `--level N` | 下载级别 1-5（默认 2） |
| `--all` | 下载全部模型 |
| `--check` | 仅检查缺失，不下载 |

---

## 模型分级

| Level | 模型数 | 大小 | 说明 |
|-------|--------|------|------|
| 1 | 15 | ~3GB | 小模型，必需 |
| 2 | +9 = 24 | ~10GB | 中等模型，推荐 |
| 3 | +4 = 28 | ~25GB | 较大模型，可选 |
| 4 | +9 = 37 | ~50GB | 大模型，部分测试需要 |
| 5 | +7 = 44 | >100GB | 超大模型，不推荐 |

---

## 常见问题

### Q: Llama 模型下载报 403 错误？

**原因**: `meta-llama/Llama-*` 在 HF 是受限仓库。

**解决**: ModelScope 上 Llama 是开放的，使用 `--source ms`：
```bash
./download_models.sh --source ms --level 2
```

### Q: 测试时连接超时？

**解决**: 设置离线环境
```bash
source hf_env.sh  # 强制 HF 离线
```

### Q: 如何跳过大模型测试？

```bash
pytest tests/test_config.py -v -k 'not 72B and not 80B and not 24B'
```

---

## 完整模型列表 (44个)

**Level 1 (~3GB)**: distilgpt2, opt-125m, e5-small, multilingual-e5-small, bge-base-en, bge-base-en-v1.5, bge-reranker-base, all-MiniLM-L12-v2, ms-marco-MiniLM-L-6-v2, whisper-tiny, clip-vit-base-patch32, siglip-base-patch16-224, mamba-130m-hf, NeuroBERT-NER, xlm-roberta-base-language-detection

**Level 2 (+~7GB)**: Qwen2.5-1.5B-Instruct, Qwen3-0.6B, Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B-seq-cls, Llama-3.2-1B-Instruct, whisper-small, gte-Qwen2-1.5B-instruct, internlm2-1_8b-reward, Qwen2.5-1.5B-apeach

**Level 3 (+~15GB)**: Qwen2.5-Math-PRM-7B, Qwen2-VL-2B-Instruct, DeepSeek-R1-Distill-Qwen-7B, granite-4.0-h-small

**Level 4 (+~25GB)**: Qwen1.5-7B, Mistral-7B-v0.1, Mistral-7B-Instruct-v0.2, Meta-Llama-3-8B-Instruct, DeepSeek-V2-Lite, longchat-13b-16k, Llama-3.1-8B-Instruct-NVFP4, Llama-3.2-1B-FP8, Qwen3-8B-speculator.eagle3

**Level 5 (>100GB)**: Qwen2.5-Math-RM-72B, Qwen3-Next-80B-A3B-Instruct, Llama-4-Scout-17B-16E-Instruct, Mixtral-8x7B-Instruct-v0.1, DeepSeek-V2.5-1210-FP8, gpt-oss-20b, Mistral-Small-24B-Instruct-2501-quantized.w8a8