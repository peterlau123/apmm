# vLLM单元测试进度跟踪

**更新时间**: 2026-05-22
**测试环境**: v0.13.0_torch2.5.1_ut容器 (NVIDIA H20-3e, 8卡)

---

## 进度概览

| 状态 | 数量 |
|------|------|
| ✅ 已完成 | 5 |
| 🔄 进行中 | 0 |
| ⏳ 待运行 | 43 |
| ❌ 已跳过 | ~246 |

---

## 已完成的测试

| 序号 | 测试目录/文件 | 日志文件 | 结果 | 备注 |
|------|--------------|---------|------|------|
| 1 | tests/basic_correctness/ | basic_ut.log | ❌ 有错误 | LoRA导入错误 |
| 2 | tests/test_config.py | config_ut.log | 26✅/89❌ | HF模型无法访问 |
| 3 | tests/v1/core/ | core_ut.log | 待检查 | |
| 4 | tests/test_inputs.py | input_ut.log | 待检查 | |
| 5 | tests/test_outputs.py | output_ut.log | 待检查 | |

---

## 待运行的测试

### tests根目录 (13个待运行)

| 序号 | 测试文件 | 日志文件 | 状态 | 结果 |
|------|---------|---------|------|------|
| 1 | test_seed_behavior.py | seed_ut.log | ⏳ | |
| 2 | test_pooling_params.py | pooling_params_ut.log | ⏳ | |
| 3 | test_triton_utils.py | triton_ut.log | ⏳ | |
| 4 | test_envs.py | envs_ut.log | ⏳ | |
| 5 | test_vllm_port.py | port_ut.log | ⏳ | |
| 6 | test_logprobs.py | logprobs_ut.log | ⏳ | |
| 7 | test_regression.py | regression_ut.log | ⏳ | |
| 8 | test_sequence.py | sequence_ut.log | ⏳ | |
| 9 | test_embedded_commit.py | commit_ut.log | ⏳ | |
| 10 | test_scalartype.py | scalartype_ut.log | ⏳ | |
| 11 | test_version.py | version_ut.log | ⏳ | |
| 12 | test_routing_simulator.py | routing_ut.log | ⏳ | |
| 13 | test_logger.py | logger_ut.log | ⏳ | |

### 子目录 (30个待运行)

| 序号 | 测试目录 | 日志文件 | 状态 | 结果 |
|------|---------|---------|------|------|
| 1 | benchmarks/ | benchmarks_ut.log | ⏳ | |
| 2 | compile/ | compile_ut.log | ⏳ | |
| 3 | config/ | config_dir_ut.log | ⏳ | |
| 4 | cuda/ | cuda_ut.log | ⏳ | |
| 5 | detokenizer/ | detokenizer_ut.log | ⏳ | |
| 6 | distributed/ | distributed_ut.log | ⏳ | 多GPU测试 |
| 7 | engine/ | engine_ut.log | ⏳ | |
| 8 | entrypoints/ | entrypoints_ut.log | ⏳ | API测试 |
| 9 | evals/ | evals_ut.log | ⏳ | |
| 10 | kernels/ | kernels_ut.log | ⏳ | CUDA kernel |
| 11 | lora/ | lora_ut.log | ⏳ | 有导入错误待修复 |
| 12 | model_executor/ | model_executor_ut.log | ⏳ | |
| 13 | models/ (部分) | models_ut.log | ⏳ | 排除特定模型 |
| 14 | plugins/ | plugins_ut.log | ⏳ | |
| 15 | plugins_tests/ | plugins_tests_ut.log | ⏳ | |
| 16 | prompts/ | prompts_ut.log | ⏳ | |
| 17 | quantization/ | quantization_ut.log | ⏳ | |
| 18 | reasoning/ (部分) | reasoning_ut.log | ⏳ | 保留minimax |
| 19 | samplers/ | samplers_ut.log | ⏳ | |
| 20 | standalone_tests/ | standalone_ut.log | ⏳ | |
| 21 | system_messages/ | system_messages_ut.log | ⏳ | |
| 22 | tokenizers_/ | tokenizers_ut.log | ⏳ | |
| 23 | tool_parsers/ | tool_parsers_ut.log | ⏳ | |
| 24 | tool_use/ | tool_use_ut.log | ⏳ | |
| 25 | tools/ | tools_ut.log | ⏳ | |
| 26 | transformers_utils/ | transformers_ut.log | ⏳ | |
| 27 | utils_/ | utils_ut.log | ⏳ | |
| 28 | v1/ (部分) | v1_ut.log | ⏳ | 排除ec/tpu |
| 29 | vllm_test_utils/ | vllm_utils_ut.log | ⏳ | |
| 30 | weight_loading/ | weight_loading_ut.log | ⏳ | |

---

## 已排除的测试

### 目录排除 (~211个文件)
- tests/**/rocm* - AMD GPU平台
- tests/**/tpu* - TPU平台
- tests/**/multimodal* - 多模态测试
- tests/**/nixl* - NVIDIA传输库
- tests/**/ec_connector* - 外部连接器

### 文件名排除 (10个)
- *image*.py, *video*.py, *audio*.py

### 特定排除 (encoder/prithvi: 11个)
- tests/**/encoder*
- tests/**/prithvi*

### 模型测试排除
- generation: gemma, granite, hybrid, mistral, phimoe
- generation_ppl_test: 全部
- pooling, pooling_mteb_test: 全部

### reasoning排除 (14个)
- deepseekr1, deepseekv3, ernie45, glm4_moe, gptoss, granite, holo2, hunyuan, mistral, olmo3, qwen3, seedoss, base_thinking

---

## 已知问题

| 问题 | 描述 | 解决方案 |
|------|------|---------|
| LoRA导入错误 | `list[torch.Tensor]` 类型不支持 | 检查PyTorch版本兼容性 |
| Triton导入失败 | `triton.language.target_info` 缺失 | Triton版本兼容性 |
| HF模型无法访问 | 未联网机器无法访问HF Hub | 预下载到/gpfs共享存储 |

---

## 测试执行命令模板

```bash
# 进入容器
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
sudo su
cd /gpfs/gcsp/M2.7_verify/vllm

# 运行单个测试
pytest -vv -s tests/test_xxx.py 2>&1 | tee ut_logs/xxx_ut.log

# 运行目录测试(带过滤)
pytest -vv -s tests/subdir/ \
  --ignore-glob="**/rocm*" \
  --ignore-glob="**/tpu*" \
  2>&1 | tee ut_logs/subdir_ut.log
```

---

## 每日更新日志

### 2026-05-22
- 创建测试进度跟踪文件
- 统计总测试文件856个
- 已完成测试5个
- 待运行测试43个