# vLLM单元测试每日汇总 - 2026-05-28

## 测试运行概况

**测试环境**: v0.13.0_torch2.5.1_compile容器 (NVIDIA H20-3e)
**测试日期**: 2026-05-28

### 累计测试统计

| 指标 | 数量 |
|------|------|
| ✅ 通过 | ~609 |
| ❌ 失败 | ~107 |
| ⚠️ 错误 | ~148 |
| **通过率** | ~71% |

### 详细测试结果（按日志文件）

| 日志文件 | 通过 | 失败 | 错误 | 备注 |
|---------|------|------|------|------|
| basic_tests_20260528_1126.log | 88 | 0 | 0 | ✅ |
| basic_tests_20260528_1218.log | 43 | 0 | 0 | ✅ |
| logprobs_envs_20260528.log | 53 | 0 | 0 | ✅ |
| engine_detokenizer_plugins | 57 | 3 | 3 | Engine初始化问题 |
| engine_ut.log | 51 | 1 | 0 | ✅ 大部分通过 |
| config_ut.log | 26 | 89 | 0 | HF模型缺失 |
| config_tools_cuda | 52 | 4 | 0 | ✅ 大部分通过 |
| routing_triton.log | 33 | 1 | 0 | ✅ 大部分通过 |
| transformers_ut.log | 22 | 2 | 0 | ✅ 大部分通过 |
| tool_plugins_prompts.log | 1 | 0 | 142 | HF离线阻塞 |
| 其他小文件 | ~100 | ~10 | ~3 | 版本检测等 |

## 修复验证

### 1. fp32_precision修复 ✅ 已验证
- **修复内容**: gpu_worker.py添加hasattr检查
- **验证结果**: 清除字节码缓存后修复生效
- **代码位置**: vllm/v1/worker/gpu_worker.py:85-86
- **状态**: 正确缩进（12空格在if块内）

### 2. LoRA类型签名修复 ✅ 已应用
- **修复内容**: list[torch.Tensor] → List[torch.Tensor]
- **验证结果**: 导入成功，不再报类型签名错误
- **状态**: 正确导入typing.List

## 发现的新问题

### 1. DeepSeek torch_compile兼容性问题 🔴 严重
```
ValueError: No dynamic dimensions found in the forward method of 
<class 'vllm.model_executor.models.deepseek_v2.DeepseekV2Model'>. 
Please provide dynamic_arg_dims explicitly.
```
- **影响**: 阻塞所有需要Engine初始化的测试
- **位置**: vllm/model_executor/models/deepseek_v2.py:1235
- **原因**: PyTorch 2.5.1 torch_compile decorator无法推断dynamic dimensions
- **待修复**: 需为DeepSeek模型添加explicit dynamic_arg_dims

### 2. 缺失依赖
| 依赖 | 类型 | 影响测试 |
|------|------|---------|
| nvshmem (libnvshmem_host.so.3) | 共享库 | routing_simulator |
| lm_eval | Python模块 | quantization, distributed |
| Snowflake/snowflake-arctic-embed-m-v1.5 | HF模型 | pooling_params |

## 待处理任务

1. **代码修复**: DeepSeek torch_compile dynamic_arg_dims问题
2. **依赖安装**: lm_eval模块
3. **模型下载**: Snowflake embedding模型
4. **继续测试**: 运行剩余测试目录

## 总结

今日完成约207个测试，fp32_precision修复已验证生效。发现新的DeepSeek torch_compile兼容性问题阻塞Engine初始化测试。需优先解决此问题才能继续测试Engine相关功能。

## 下一步行动计划

1. **紧急**: 修复DeepSeek torch_compile dynamic_arg_dims问题
2. **高优先**: 安装缺失模块(lm_eval)
3. **中优先**: 下载缺失模型(Snowflake)
4. **待定**: 修复deep_gemm ABI兼容性问题