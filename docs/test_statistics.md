# vLLM单元测试统计报告

## 已运行的测试 (ut_logs目录)

| 日志文件 | 测试范围 | 状态 |
|---------|---------|------|
| basic_ut.log | tests/basic_correctness/ | ✅ 已运行 (有导入错误) |
| config_ut.log | tests/test_config.py | ✅ 已运行 (89失败26通过) |
| core_ut.log | tests/v1/core/ | ✅ 已运行 |
| input_ut.log | tests/test_inputs.py | ✅ 已运行 |
| output_ut.log | tests/test_outputs.py | ✅ 已运行 |

## 排除的测试

### 目录排除 (211个文件)
- tests/**/rocm* - AMD GPU平台
- tests/**/tpu* - TPU平台
- tests/**/multimodal* - 多模态测试
- tests/**/nixl* - NVIDIA传输库
- tests/**/ec_connector* - 外部连接器

### 文件名排除 (10个文件)
- tests/**/*image*.py - 图像测试
- tests/**/*video*.py - 视频测试
- tests/**/*audio*.py - 音频测试

### 特定文件排除 (encoder/prithvi: 11个文件)
- tests/**/encoder* - 编码器测试
- tests/**/prithvi* - Prithvi模型测试

### 模型测试排除
- tests/models/language/generation/: test_gemma.py, test_granite.py, test_hybrid.py, test_mistral.py, test_phimoe.py
- tests/models/language/generation_ppl_test/: test_gemma.py, test_gpt.py, test_qwen.py
- tests/models/language/pooling/ - 全部排除
- tests/models/language/pooling_mteb_test/ - 全部排除

### reasoning测试排除 (14个文件)
- test_deepseekr1_reasoning_parser.py
- test_deepseekv3_reasoning_parser.py
- test_ernie45_reasoning_parser.py
- test_glm4_moe_reasoning_parser.py
- test_gptoss_reasoning_parser.py
- test_granite_reasoning_parser.py
- test_holo2_reasoning_parser.py
- test_hunyuan_reasoning_parser.py
- test_mistral_reasoning_parser.py
- test_olmo3_reasoning_parser.py
- test_qwen3_reasoning_parser.py
- test_seedoss_reasoning_parser.py
- test_base_thinking_reasoning_parser.py

## 待运行的测试目录

### tests根目录 (13个待运行)
| 序号 | 测试文件 | 日志文件 |
|------|---------|---------|
| 1 | test_seed_behavior.py | seed_ut.log |
| 2 | test_pooling_params.py | pooling_params_ut.log |
| 3 | test_triton_utils.py | triton_ut.log |
| 4 | test_envs.py | envs_ut.log |
| 5 | test_vllm_port.py | port_ut.log |
| 6 | test_logprobs.py | logprobs_ut.log |
| 7 | test_regression.py | regression_ut.log |
| 8 | test_sequence.py | sequence_ut.log |
| 9 | test_embedded_commit.py | commit_ut.log |
| 10 | test_scalartype.py | scalartype_ut.log |
| 11 | test_version.py | version_ut.log |
| 12 | test_routing_simulator.py | routing_ut.log |
| 13 | test_logger.py | logger_ut.log |

### 子目录 (部分)
| 序号 | 测试目录 | 日志文件 | 备注 |
|------|---------|---------|------|
| 1 | benchmarks/ | benchmarks_ut.log | |
| 2 | compile/ | compile_ut.log | |
| 3 | config/ | config_dir_ut.log | |
| 4 | cuda/ | cuda_ut.log | |
| 5 | detokenizer/ | detokenizer_ut.log | |
| 6 | distributed/ | distributed_ut.log | 多GPU测试 |
| 7 | engine/ | engine_ut.log | |
| 8 | entrypoints/ | entrypoints_ut.log | API测试 |
| 9 | evals/ | evals_ut.log | |
| 10 | kernels/ | kernels_ut.log | CUDA kernel测试 |
| 11 | lora/ | lora_ut.log | 有导入错误待修复 |
| 12 | model_executor/ | model_executor_ut.log | |
| 13 | models/ (部分) | models_ut.log | 排除特定模型 |
| 14 | plugins/ | plugins_ut.log | |
| 15 | plugins_tests/ | plugins_tests_ut.log | |
| 16 | prompts/ | prompts_ut.log | |
| 17 | quantization/ | quantization_ut.log | |
| 18 | reasoning/ (部分) | reasoning_ut.log | 保留minimax相关 |
| 19 | samplers/ | samplers_ut.log | |
| 20 | standalone_tests/ | standalone_ut.log | |
| 21 | system_messages/ | system_messages_ut.log | |
| 22 | tokenizers_/ | tokenizers_ut.log | |
| 23 | tool_parsers/ | tool_parsers_ut.log | |
| 24 | tool_use/ | tool_use_ut.log | |
| 25 | tools/ | tools_ut.log | |
| 26 | transformers_utils/ | transformers_ut.log | |
| 27 | utils_/ | utils_ut.log | |
| 28 | v1/ (部分) | v1_ut.log | 排除ec_connector, tpu |
| 29 | vllm_test_utils/ | vllm_utils_ut.log | |
| 30 | weight_loading/ | weight_loading_ut.log | |

## 统计汇总

| 类别 | 数量 |
|------|------|
| 总测试文件 | 856个 |
| 排除的测试文件 | ~246个 (目录211 + 文件名10 + encoder/prithvi 11 + 特定模型14) |
| 待运行测试目录 | ~43个 (13个根文件 + 30个子目录) |

## 执行优先级建议

### 第一优先级 (基础功能测试)
1. tests/test_seed_behavior.py
2. tests/test_version.py
3. tests/test_logger.py
4. tests/tokenizers_/
5. tests/detokenizer/

### 第二优先级 (核心组件)
1. tests/engine/
2. tests/samplers/
3. tests/kernels/
4. tests/config/
5. tests/cuda/

### 第三优先级 (高级功能)
1. tests/quantization/
2. tests/lora/ (需先修复导入错误)
3. tests/distributed/
4. tests/entrypoints/

### 第四优先级 (模型相关)
1. tests/models/ (保留的部分)
2. tests/model_executor/
3. tests/weight_loading/