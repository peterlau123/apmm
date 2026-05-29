# vLLM单元测试进度跟踪

**更新时间**: 2026-05-29
**测试环境**: v0.13.0_torch2.5.1_compile容器 (NVIDIA H20-3e, 8卡)

---

## 进度概览

| 指标 | 数量 |
|------|------|
| ✅ 通过 | **~860+** |
| ❌ 失败 | ~143 |
| ⚠️ 错误 | ~20 (HF离线) |
| **通过率** | ~85% |

**重大进展**: ✅ DeepSeek torch_compile修复成功并提交！

---

## 本次会话测试结果

### 根目录测试
| 测试文件 | 通过 | 失败 | 备注 |
|---------|------|------|------|
| test_logger.py | 22 | 0 | ✅ |
| test_scalartype.py | 12 | 0 | ✅ |
| test_sequence.py | 1 | 0 | ✅ |
| test_seed_behavior.py | 1 | 0 | ✅ |
| test_vllm_port.py | 4 | 0 | ✅ |
| test_embedded_commit.py | 1 | 0 | ✅ |
| test_outputs.py | 1 | 0 | ✅ |
| test_version.py | 7 | 6 | 已知版本检测问题 |
| test_inputs.py | 19 | 0 | 2 skipped |
| test_logprobs.py + test_envs.py | 53 | 0 | ✅ |
| test_routing_simulator.py | 26 | 1 | nvshmem缺失 |
| test_triton_utils.py | 7 | 0 | ✅ |

### 子目录测试
| 测试目录 | 通过 | 失败 | 备注 |
|---------|------|------|------|
| tools/ | 4 | 0 | ✅ |
| cuda/ | 4 | 0 | ✅ |
| engine/test_arg_utils.py | 51 | 0 | ✅ |
| model_executor/custom_ops | 20 | 0 | 12 skipped |
| model_executor/eagle_quantization | 8 | 0 | ✅ |
| compile/test_noop_elimination.py | 25 | 0 | ✅ |
| kernels/shuffle_rows | 158 | 1 | ✅ |
| kernels/top_k_per_row | 31 | 0 | ✅ |
| kernels/fused_quant_activation | 100 | 0 | ✅ |
| kernels/onednn | 0 | 0 | 1 skipped |
| kernels/cache_kernels | 0 | 1 | OOB测试失败 |
| engine/ (2026-05-29) | 51 | 1 | ✅ 大部分通过 |
| detokenizer/ (2026-05-29) | 5 | 2 | 1 error |
| samplers/ (2026-05-29) | 0 | 10 | HF模型缺失 |
| v1/ (2026-05-29) | - | - | 18 collection errors (TPU/HF) |
| entrypoints/ (2026-05-29) | - | - | 10 collection errors (HF/lm_eval) |

### 累计日志测试结果
| 日志文件 | 通过 | 失败 | 错误 |
|---------|------|------|------|
| basic_tests_1126.log | 88 | 0 | 0 |
| basic_tests_1218.log | 43 | 0 | 0 |
| engine_detokenizer_plugins.log | 57 | 3 | 3 |
| engine_ut.log | 51 | 1 | 0 |
| config_ut.log | 26 | 89 | 0 |
| config_dir_ut.log | 22 | 3 | 0 |
| config_tools_cuda.log | 52 | 4 | 0 |
| transformers_ut.log | 22 | 2 | 0 |

---

## 关键阻塞问题

### ✅ DeepSeek torch_compile修复 (2026-05-29完成)
- **文件**: `vllm/model_executor/models/deepseek_v2.py:1235`
- **修复**: `{input_ids: 0, positions: 0}` → `{"input_ids": 0, "positions": 0}`
- **提交**: `15565df57` on branch `2.5.1_ut_verify`
- **状态**: ✅ 已提交

---

## 已修复的问题

### ✅ fp32_precision兼容性修复
- **文件**: `vllm/v1/worker/gpu_worker.py:85-86`
- **修复**: 添加`hasattr(torch.backends.cuda.matmul, "fp32_precision")`检查
- **状态**: 已验证生效

### ✅ LoRA类型签名修复
- **文件**: `lora_expand_op.py`, `lora_shrink_op.py`, `fused_moe_lora_op.py`
- **修复**: `list[torch.Tensor]` → `List[torch.Tensor]`
- **状态**: 已应用

---

## 缺失依赖

| 依赖 | 影响测试 |
|------|---------|
| lm_eval模块 | quantization, distributed |
| nvshmem库 | routing_simulator |
| Snowflake模型 | pooling_params |
| TinyLlama模型 | samplers |

---

## 待运行测试目录

- samplers/ (需DeepSeek修复)
- distributed/ (需lm_eval)
- quantization/ (需lm_eval)
- v1/ (需DeepSeek修复)
- models/ (需HF模型)
- detokenizer/ (需DeepSeek修复)
- entrypoints/ (需DeepSeek修复)
- lora/ (需HF模型)

---

## 更新日志

**2026-05-29 会话**:
- ✅ DeepSeek torch_compile引号问题已修复并提交 (`15565df57`)
- ✅ 文档整理完成：新结构 guides/reports/reference
- ✅ 测试执行：engine (51p), detokenizer (5p)
- ⏳ samplers/v1/entrypoints 受HF模型缺失影响
- 通过率提升至 ~85% (累计 ~860+ passed)

**2026-05-28 会话**:
- 累计通过测试 ~700+
- 新增kernel测试: shuffle_rows (158p), fused_quant_activation (100p)
- DeepSeek修复尝试被阻止，需手动执行
- 文档结构化整理完成