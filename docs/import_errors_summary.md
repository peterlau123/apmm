# vLLM单元测试导入错误汇总

**记录时间**: 2026-05-25 02:15
**测试环境**: v0.13.0_torch2.5.1_compile容器 (NVIDIA H20-3e × 8)

---

## 文件说明

**导引路径**: `docs/test_summary.md` → 本文件

**文件用途**: 记录vLLM单元测试运行过程中遇到的所有导入错误，用于：
1. 快速定位测试失败的根本原因（区分依赖缺失vs代码问题）
2. 为后续修复提供优先级参考
3. 避免重复排查相同问题

**关联文档**:
- `docs/README.md` - 单元测试执行指南（总体流程）
- `docs/test_summary.md` - 测试结果汇总（最终统计数据）
- `PROGRESS.md` - 进度跟踪（实时更新）

---

## 导入错误分类

### 1. LoRA类型签名错误 (最普遍)

**错误信息**:
```
ValueError: infer_schema(func): Parameter lora_a_stacked has unsupported type list[torch.Tensor].
The valid types are: dict_keys([<class 'torch.Tensor'>, ...])
```

**原因**: PyTorch 2.5.1版本与vLLM LoRA自定义算子的类型签名不兼容。vLLM使用了`list[torch.Tensor]`类型注解，但PyTorch的`infer_schema`只支持`typing.List[torch.Tensor]`。

**影响范围**:
| 测试目录 | 错误数量 |
|---------|---------|
| tests/entrypoints/ | 3 |
| tests/kernels/ | 10+ |
| tests/distributed/ | 3 |
| tests/quantization/ | 9 |
| tests/compile/ | 2 |
| tests/utils_/ | 1 |
| tests/lora/ | (预期全部失败) |

**解决方案**: 需检查PyTorch版本兼容性，可能需要patch类型签名或将`list[torch.Tensor]`改为`typing.List[torch.Tensor]`

---

### 2. Python模块缺失错误

| 缺失模块 | 影响测试文件 | 用途 |
|---------|-------------|------|
| `mteb` | tests/entrypoints/pooling/embed/test_correctness_mteb.py | MTEB基准测试 |
| `mteb` | tests/entrypoints/pooling/score/test_correctness_mteb.py | MTEB基准测试 |
| `multiprocess` | tests/distributed/test_pynccl.py | 多进程通信 |
| `vllm_test_utils` | tests/utils_/test_mem_utils.py | vLLM测试工具包 |
| `grpc` | tests/v1/tracing/test_tracing.py | 分布式追踪 |
| `dummy_stat_logger` | tests/plugins_tests/test_stats_logger_plugins.py | 统计日志插件 |

**解决方案**: 在t_ascend下载pip包，通过/gpfs共享安装
```bash
# 在t_ascend下载
pip download mteb multiprocess -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/

# 在容器安装
pip install /gpfs/.../mteb.whl
```

---

### 3. PyTorch版本兼容问题

| 错误 | 缺失API/属性 | 影响测试 |
|-----|-------------|---------|
| `ImportError: cannot import name 'wrap_triton' from 'torch.library'` | `torch.library.wrap_triton` | tests/quantization/test_rtn.py等 |
| `AttributeError: torch._dynamo.config.recompile_limit does not exist` | `torch._dynamo.config.recompile_limit` | tests/kernels/test_flex_attention.py |
| `AttributeError: Unknown attribute fp32_precision` | `torch.backends.cuda.matmul.fp32_precision` | tests/config/test_mp_reducer.py, tests/samplers/, tests/v1/worker/ |

**原因**: 容器内PyTorch版本(2.5.1)缺少vLLM依赖的部分API，可能是vLLM代码针对更新的PyTorch版本开发。

**影响范围**: 
- ✅ 已确认影响：config、samplers、v1/worker测试
- ⚠️ 潜在影响：任何需要启动Engine的测试都会失败

**解决方案**: 需确认vLLM v0.13.0对PyTorch版本的要求，或升级容器内PyTorch

**代码位置**: 
```
vllm/v1/worker/gpu_worker.py:85:
    torch.backends.cuda.matmul.fp32_precision = precision
```

---

### 4. 分布式环境变量缺失

**错误信息**:
```
ValueError: Error initializing torch.distributed using env:// rendezvous:
environment variable RANK expected, but not set
```

**影响测试**:
- tests/distributed/test_torchrun_example.py
- tests/distributed/test_torchrun_example_moe.py
- tests/distributed/test_ca_buffer_sharing.py

**原因**: 这些测试需要在torchrun环境下运行，而非直接pytest执行

**解决方案**: 使用`torchrun --nproc_per_node=N pytest tests/...`方式运行分布式测试

---

### 5. HuggingFace离线模式缓存缺失

**错误信息**:
```
LocalEntryNotFoundError: Cannot find an appropriate cached snapshot folder for
the specified revision on the local disk and outgoing traffic has been disabled.
```

**影响测试**:
- tests/kernels/quantization/test_gguf.py

**原因**: 测试需要从HF Hub下载模型，但t_h20未联网且本地缓存中无所需模型

**解决方案**: ✅ 设置本地HF_HUB路径可以解决
```bash
# 设置环境变量
export HF_HOME=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
export HF_HUB_CACHE=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 或在t_ascend预先下载缺失模型
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download <model_id> --local-dir /gpfs/.../hf_hub/hub/<model_dir>
```

**已有本地模型**:
- facebook/opt-125m
- distilbert/distilgpt2
- Qwen/Qwen3-0.6B

---

## 错误统计汇总

| 错误类型 | 测试目录受影响数 | 是否可修复 |
|---------|-----------------|-----------|
| LoRA类型签名 | 7+ | 需patch代码或升级PyTorch |
| 模块缺失 | 4 | ✅ 可pip安装 |
| PyTorch API缺失 | 3 | 需升级PyTorch版本 |
| 分布式环境变量 | 3 | ✅ 可用torchrun运行 |
| HF离线缓存 | 1+ | ✅ 可设置本地路径 |

---

## 后续建议

1. **优先处理可修复问题**:
   - 安装缺失模块: mteb, multiprocess
   - 设置HF离线环境变量

2. **记录但不修复的问题**:
   - LoRA类型签名问题 (影响最广，需代码patch)
   - PyTorch API兼容问题

3. **分布式测试**: 使用torchrun而非pytest直接运行