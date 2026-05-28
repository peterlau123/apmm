# vLLM单元测试最终汇总

**测试日期**: 2026-05-25
**测试环境**: v0.13.0_torch2.5.1_compile容器 (NVIDIA H20-3e × 8)
**更新时间**: 2026-05-25 02:15

---

## 文档索引

| 文档 | 用途 | 导引关系 |
|------|------|---------|
| `docs/README.md` | 单元测试执行指南 | 主入口 |
| `docs/test_summary.md` | 测试结果汇总 | ← 本文件 |
| `docs/import_errors_summary.md` | 导入错误详细分类 | ← 本文件（失败原因详情） |
| `PROGRESS.md` | 进度跟踪 | 实时状态 |

---

## 测试统计

| 指标 | 数量 |
|------|------|
| ✅ 通过测试 | ~250+ |
| ❌ 失败测试 | ~200+ (主要网络/模型问题) |
| ⚠️ 导入错误 | ~50+ |
| 🔴 网络错误 | ~200+ |
| 📁 日志文件数 | 48 |

---

## 各测试目录结果汇总

### tests根目录

| 测试文件 | 通过 | 失败 | 错误 | 主要问题 |
|---------|------|------|------|---------|
| test_seed_behavior.py | 1 | 0 | 0 | ✅ |
| test_version.py | 7 | 6 | 0 | 版本检测逻辑 |
| test_logger.py | 22 | 0 | 0 | ✅ |
| test_sequence.py | 1 | 0 | 0 | ✅ |
| test_scalartype.py | 12 | 0 | 0 | ✅ |
| test_embedded_commit.py | 1 | 0 | 0 | ✅ |
| test_vllm_port.py | 4 | 0 | 0 | ✅ |
| test_pooling_params.py | 9 | 1 | 0 | Snowflake模型缺失 |
| test_logprobs.py + test_envs.py | 53 | 0 | 0 | ✅ |
| test_routing_simulator + test_triton_utils | 33 | 1 | 0 | nvshmem库缺失 |
| test_config.py | 26 | 89 | 0 | HF模型无法访问 |

### tests子目录

| 测试目录 | 通过 | 失败 | 错误 | 主要问题 |
|---------|------|------|------|---------|
| cuda/ | 4 | 0 | 0 | ✅ **全部通过** |
| tools/ | 4 | 0 | 0 | ✅ **全部通过** |
| config/ | 22 | 3 | 0 | fp32_precision属性缺失 |
| transformers_utils/ | 22 | 2 | 0 | HF网络问题 |
| engine/ | 51 | 1 | 0 | 网络下载资产问题 |
| basic_correctness/ | 部分 | 部分 | 有 | LoRA导入错误 |
| samplers/ | 0 | 10 | 1 | Engine初始化失败 |
| detokenizer/ | 5 | 2 | 1 | 模型缺失 |
| tokenizers_/ | 部分 | 大量 | 0 | 网络问题 |
| plugins/ | 1 | 0 | 2 | HF离线 |
| entrypoints/ | - | - | 3 | LoRA+mteb缺失 |
| kernels/ | - | - | 14 | LoRA+HF离线+dynamo |
| distributed/ | - | - | 6 | LoRA+环境变量+multiprocess |
| quantization/ | - | - | 9 | LoRA+wrap_triton缺失 |
| compile/ | - | - | 2 | LoRA |
| utils_/ | - | - | 2 | LoRA+vllm_test_utils缺失 |
| model_executor/ | 63 collected | - | 1 | LoRA |
| tool_use/ | - | - | 有 | LoRA |
| v1/ | - | - | 22 | LoRA+HF+grpc+TPU |
| reasoning/ | - | - | 30 | HF离线 |
| weight_loading/ | 0 | 1 | 0 | HF离线 |
| benchmarks/ | - | - | 2 | LoRA |
| plugins_tests/ | - | - | 2 | LoRA+dummy_stat_logger缺失 |
| tool_parsers/ | - | - | 140 | HF离线 |
| lora/ | - | - | 4 | LoRA签名+HF离线 |
| prompts/ | 0 | 0 | 0 | 无测试文件 |
| standalone_tests/ | 0 | 0 | 0 | 无测试文件 |
| system_messages/ | 0 | 0 | 0 | 无测试文件 |
| vllm_test_utils/ | 0 | 0 | 0 | 无测试文件 |

---

## 失败原因分类

详细错误分析见: **[docs/import_errors_summary.md](import_errors_summary.md)**

### 按错误类型统计

| 错误类型 | 影响测试数 | 占比 |
|---------|-----------|------|
| LoRA类型签名错误 | 15+目录 | ~30% |
| HF网络/离线问题 | 10+目录 | ~60% |
| Python模块缺失 | 5个模块 | ~5% |
| PyTorch API缺失 | 3个属性 | ~3% |
| 分布式环境变量 | 3个测试 | ~2% |

---

## 已发现的缺失依赖

### Python模块 (可pip安装)
| 缺失模块 | 用途 |
|---------|------|
| mteb | MTEB基准测试 |
| multiprocess | 多进程通信 |
| vllm_test_utils | 测试工具包 |
| dummy_stat_logger | 统计日志插件 |
| grpc | 分布式追踪 |

### PyTorch兼容性问题 (需代码patch)
| 缺失API | 影响 |
|---------|------|
| torch.library.wrap_triton | quantization测试 |
| torch._dynamo.config.recompile_limit | flex_attention测试 |
| torch.backends.cuda.matmul.fp32_precision | config测试 |

### LoRA类型签名问题 (影响最广)
```
ValueError: infer_schema(func): Parameter lora_a_stacked has unsupported type list[torch.Tensor]
```
需将`list[torch.Tensor]`改为`typing.List[torch.Tensor]`

---

## 完全通过的测试目录

| 目录 | 通过数 | 说明 |
|------|--------|------|
| tests/cuda/ | 4 | CUDA上下文测试 |
| tests/tools/ | 4 | 配置验证器测试 |

---

## 后续建议

1. **优先修复可解决的问题**:
   - 安装缺失模块: mteb, multiprocess, grpc
   - 设置HF离线环境变量并预下载模型

2. **记录但不修复的问题**:
   - LoRA类型签名问题 (需代码patch)
   - PyTorch API兼容问题 (需版本升级)

3. **测试通过的关键目录**:
   - tests/cuda/ (✅ 4 passed)
   - tests/tools/ (✅ 4 passed)
   - tests/config/ (22 passed, 3 failed)
   - tests/transformers_utils/ (22 passed, 2 failed)

---

## 待执行修复方案

以下修复需手动执行（daemon输出捕获异常）：

### 1. 安装缺失Python模块

**在t_ascend（联网机器）执行：**
```bash
# 下载包到共享存储
cd /gpfs/gcsp/M2.7_verify/vllm/
pip3 download grpcio mteb multiprocess --no-deps
```

**在t_h20容器内执行：**
```bash
# 进入容器
sudo docker exec -it v0.13.0_torch2.5.1_compile bash

# 安装包
pip install /gpfs/gcsp/M2.7_verify/vllm/grpcio*.whl
pip install /gpfs/gcsp/M2.7_verify/vllm/mteb*.whl
pip install /gpfs/gcsp/M2.7_verify/vllm/multiprocess*.whl
```

### 2. HF离线环境变量 (✅ 已配置)

已在容器内创建配置文件：
```bash
# ~/.config/vllm_test_env.sh
export HF_HOME=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

**运行测试时使用：**
```bash
# 进入容器后先加载环境
source ~/.config/vllm_test_env.sh

# 然后运行pytest
pytest -vv tests/xxx/
```

**或一行执行：**
```bash
docker exec v0.13.0_torch2.5.1_compile bash -c 'source ~/.config/vllm_test_env.sh && pytest tests/xxx/'
```

---

## 文档更新记录

- 2026-05-25 02:05 - 创建docs/import_errors_summary.md
- 2026-05-25 02:15 - 完成所有测试目录运行，更新最终汇总
- 2026-05-25 02:30 - HF离线环境验证：test_config.py通过率从22%提升至77%
- 2026-05-26 11:30 - 重跑简单测试：logger/scalartype/sequence/tools/cuda/transformers_utils 全部通过
- 2026-05-26 11:35 - 磁盘配额超限，无法下载新模型
- 2026-05-26 12:00 - 新增测试结果：pooling_params/vllm_port/embedded_commit/routing_simulator/triton_utils/logprobs/envs/config/engine/detokenizer/plugins/version，总计313通过
- 2026-05-26 14:00 - 磁盘分析：mle-bench-lite-download占用354G，用户配额超限无法下载Snowflake模型
- 2026-05-26 14:30 - Snowflake模型已下载到t_ascend/tmp(2.7G)，但因配额限制无法复制到HF缓存

---

## 本次会话测试结果汇总

| 测试目录 | 通过数 | 失败数 | 状态 |
|---------|--------|--------|------|
| tests/test_logger.py | 22 | 0 | ✅ 全部通过 |
| tests/test_scalartype.py | 12 | 0 | ✅ 全部通过 |
| tests/test_sequence.py | 1 | 0 | ✅ 全部通过 |
| tests/tools/ | 4 | 0 | ✅ 全部通过 |
| tests/cuda/ | 4 | 0 | ✅ 全部通过 |
| tests/transformers_utils/ (排除llama/blip) | 22 | 0 | ✅ 全部通过 |
| tests/test_config.py (HF离线) | 89 | 26 | 77%通过率 |
| tests/test_pooling_params.py | 9 | 1 | Snowflake模型缺失 |
| tests/test_vllm_port.py | 4 | 0 | ✅ 全部通过 |
| tests/test_embedded_commit.py | 1 | 0 | ✅ 全部通过 |
| tests/test_routing_simulator.py + test_triton_utils.py | 33 | 1 | 分布式测试失败 |
| tests/test_logprobs.py + test_envs.py | 53 | 0 | ✅ 全部通过 |
| tests/config/ | 22 | 3 | DeepSeek模型+fp32_precision |
| tests/engine/test_arg_utils.py | 51 | 0 | ✅ 全部通过 |
| tests/detokenizer/ | 5 | 2+1 | 模型缺失+Engine初始化 |
| tests/plugins/ | 1 | 2 | LoRA模型缺失 |
| tests/test_version.py | 7 | 6 | 版本检测逻辑问题 |
| tests/model_executor/test_enabled_custom_ops.py | 20 | 0 (12 skip) | ✅ 通过 |
| tests/model_executor/test_eagle_quantization.py | 8 | 0 | ✅ 全部通过 |

**总计本次通过**: 341个测试
**总计本次失败**: 约43个测试（主要为模型缺失问题）
**总计跳过**: 12个测试

---

## Snowflake模型说明

**模型名称**: `Snowflake/snowflake-arctic-embed-m-v1.5`
**模型大小**: 2.7G
**模型类型**: Embedding模型（BERT架构）

**用途**: 测试vLLM的embedding/pooling功能
- `test_pooling_params.py::test_embed_dimensions` - 测试embedding维度参数

**当前状态**:
- ✅ 模型文件已复制到 `/gpfs/.../hub/models--Snowflake--snowflake-arctic-embed-m-v1.5/snapshots/e58a8f756156a1293d763f17e3aae643474e9b8a/`
- ✅ 可通过本地路径加载模型
- ❌ HF缓存metadata结构不完整，无法通过模型ID在HF离线模式访问

**修复建议**: 需要补充HF缓存metadata文件（`.cache/huggingface/download/*.metadata`）才能在离线模式使用模型ID

---

## 磁盘占用分析与清理建议

### 大型HF缓存模型 (可清理)

| 模型 | 大小 | 建议 |
|------|------|------|
| granite-4.0-h-small | 60G | ⚠️ 可清理（非vLLM测试用） |
| Llama-3-8B (2个版本) | 30G×2=60G | ⚠️ 部分可清理 |
| Mistral-7B-v0.3 (2个版本) | 28G×2=56G | ⚠️ 部分可清理 |
| longchat-13b-16k | 25G | ⚠️ 可清理（非vLLM测试用） |
| DeepSeek-R1-Distill-Qwen-7B | 15G | ⚠️ 可清理 |

### 建议清理命令
```bash
# 清理非测试必需的大模型
rm -rf /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub/models--ibm--granite-4.0-h-small
rm -rf /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub/models--lmsys--longchat-13b-16k
rm -rf /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub/models--deepseek-ai--DeepSeek-R1-Distill-Qwen-7B

# 预估释放空间: ~100G
```

### ModelScope缓存 (不可用)
- ModelScope下载的Llama模型只有`.mdl`元数据文件（57字节）
- 无法直接用于HuggingFace `from_pretrained`
- 建议使用HuggingFace标准格式下载

---

## 已知阻塞问题

| 问题 | 影响 | 解决方案 |
|------|------|---------|
| 磁盘配额超限 | 无法下载新模型 | 申请更多配额或清理旧文件 |
| PyTorch fp32_precision缺失 | Engine启动测试失败 | 需PyTorch版本升级或代码patch |
| LoRA类型签名错误 | 多个目录导入失败 | 需代码patch类型签名 |
| Llama受限模型 | 无法下载 | 需在HF申请授权 |
| ModelScope缓存不兼容 | 无法使用ModelScope下载的模型 | ModelScope模型只有.mdl元数据文件，无实际权重 |

---

## HF离线环境验证结果

**验证时间**: 2026-05-25

使用 `tests/test_config.py` 验证HF离线环境效果：

| 指标 | 之前(无HF离线) | 现在(有HF离线) | 变化 |
|------|---------------|---------------|------|
| ✅ 通过 | 26 | 89 | +63 |
| ❌ 失败 | 89 | 26 | -63 |
| 通过率 | 22% | 77% | +55% |

**结论**: HF离线环境有效，但部分模型缓存不完整。

**缓存状态检查**:
```bash
# 完整模型（可加载）: opt-125m, distilgpt2, Qwen系列
# 不完整模型（仅有LICENSE/README）: Llama-3.2-1B-Instruct等
ls /gpfs/.../models--meta-llama--Llama-3.2-1B-Instruct/snapshots/*/
# 只有 LICENSE.txt, README.md
```

**需要补充下载的模型**（在t_ascend执行）:
```bash
# 非受限模型可直接下载
huggingface-cli download TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
  --local-dir /gpfs/.../hf_hub/hub/models--TinyLlama--TinyLlama-1.1B-Chat-v1.0

# 受限模型需要先申请授权
# 1. 访问 https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct
# 2. 点击 "Request access" 并同意条款
# 3. 等待批准后才能下载
```