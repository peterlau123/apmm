# PyTorch 2.5.1 vLLM 测试指南

## 目录结构

```
ut/
├── scripts/
│   ├── download_models_for_tests.sh  # 联网机器下载模型
│   ├── hf_env.sh                     # 离线环境配置
│   ├── run_filtered_tests.sh         # 运行测试
│   └── convert_to_markdown.sh        # 生成报告
│
├── patches/
│   ├── torch_compat.py               # auto_functionalized 兼容层
│   ├── apply_auto_functionalized_patch.sh
│   └── README.md                     # 修改指南
│
├── hf_hub/                           # HuggingFace 缓存（下载后）
│   ├── hub/
│   ├── transformers/
│   └── datasets/
│
└── dependencies/
    ├── parallel-latest.tar.bz2       # GNU parallel
    ├── install_parallel.sh
    └── *.whl                         # Python 依赖包
```

---

## 步骤 1: 联网机器准备

### 1.1 下载 Python 依赖
```bash
pip download pytest pytest-asyncio pytest-cov pytest-forked \
    pytest-rerunfailures pytest-shard pytest-timeout huggingface_hub \
    psutil gguf cbor2 aiohttp pyzmq \
    --dest /path/to/ut/dependencies/
```

### 1.2 安装 GNU parallel
```bash
cd ut/dependencies/
./install_parallel.sh
```

### 1.3 下载测试所需模型

**前提**: 已修复 PyTorch 兼容性问题

```bash
cd ut/scripts/
./download_models_for_tests.sh --tests-dir /path/to/vllm/tests
```

脚本会：
1. 收集过滤后的测试
2. 分析测试需要的模型
3. 使用 HF 镜像下载到 `hf_hub/`

如果 pytest collect 失败（兼容性问题未修复），脚本会使用预定义模型列表。

### 1.4 复制到离线机器

复制整个 `ut/` 目录到离线机器。

---

## 步骤 2: 离线机器设置

### 2.1 安装 Python 依赖
```bash
pip install --no-index --find-links=/path/to/ut/dependencies/ \
    pytest pytest-asyncio pytest-cov pytest-forked \
    pytest-rerunfailures pytest-shard pytest-timeout \
    huggingface_hub psutil gguf cbor2 aiohttp pyzmq
```

### 2.2 安装 GNU parallel
```bash
cd ut/dependencies/
./install_parallel.sh
```

### 2.3 配置 HuggingFace 环境变量
```bash
source ut/scripts/hf_env.sh
```

或手动设置：
```bash
export HF_HOME=/path/to/ut/hf_hub
export HF_HUB_CACHE=/path/to/ut/hf_hub/hub
export TRANSFORMERS_CACHE=/path/to/ut/hf_hub/transformers
export HF_DATASETS_CACHE=/path/to/ut/hf_hub/datasets
```

---

## 步骤 3: 修复 PyTorch 兼容性

在 vllm 源码根目录执行：

```bash
# 应用 auto_functionalized 兼容补丁
cp ut/patches/torch_compat.py vllm/compilation/
cd vllm/

# 手动修改导入（或使用脚本）
for f in compilation/matcher_utils.py compilation/fusion_attn.py \
         compilation/fix_functionalization.py compilation/collective_fusion.py \
         compilation/qk_norm_rope_fusion.py compilation/fx_utils.py \
         compilation/fusion.py compilation/activation_quant_fusion.py; do
    sed -i 's/from torch\._higher_order_ops.*auto_functionalized/from vllm.compilation.torch_compat import auto_functionalized/' "$f"
done

# 修改 tests/conftest.py (fresh_cache)
sed -i 's/from torch._inductor.utils import fresh_cache/from contextlib import nullcontext\ntry:\n    from torch._inductor.utils import fresh_cache\nexcept ImportError:\n    fresh_cache = nullcontext/' tests/conftest.py

# 修改 vllm/distributed/parallel_state.py (list[int])
sed -i 's/from typing import Any, Optional/from typing import Any, List, Optional/' vllm/distributed/parallel_state.py
sed -i 's/output_shape: list\[int\]/output_shape: List[int]/g' vllm/distributed/parallel_state.py
```

---

## 步骤 4: 运行测试

```bash
# 测试模式 - 验证输出格式（10个测试）
cd ut/scripts/
./run_filtered_tests.sh --tests-dir /path/to/vllm/tests --test

# 全量测试
./run_filtered_tests.sh --tests-dir /path/to/vllm/tests

# 生成 Markdown 报告
./convert_to_markdown.sh
```

---

## 环境变量参考

| 变量 | 作用 | 示例值 |
|------|------|--------|
| `HF_HOME` | HF 缓存主目录 | `/path/to/hf_hub` |
| `HF_HUB_CACHE` | 模型缓存 | `${HF_HOME}/hub` |
| `TRANSFORMERS_CACHE` | transformers 缓存 | `${HF_HOME}/transformers` |
| `HF_HUB_OFFLINE` | 强制离线模式 | `1` |
| `HF_ENDPOINT` | HF 镜像地址 | `https://hf-mirror.com` |

---

## 常见问题

### Q: pytest collect 失败
检查 PyTorch 兼容性问题是否已修复：
```bash
python -c "from vllm.compilation.backends import VllmBackend"
```

### Q: 模型下载失败
检查 HF 镜像是否可用：
```bash
curl -I https://hf-mirror.com
```

### Q: 测试找不到模型
检查 HF 环境变量是否正确设置：
```bash
echo $HF_HOME
ls -la $HF_HUB_CACHE
```