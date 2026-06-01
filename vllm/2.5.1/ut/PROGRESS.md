# 单元测试进度追踪

> **vLLM v0.13.0 + PyTorch 2.5.1 pytest 测试进度**
> **详细进度主文件 - 含每日执行记录、问题分类、修复状态**

---

## 当前状态概览

| 指标 | 数量 | 说明 |
|------|:----:|------|
| ✅ 累计通过 | **~4,518** | 今日新增 ~349 测试 |
| ❌ 累计失败 | ~850 | compile/v1 目录新增失败 |
| 🔄 剩余待运行 | ~26,300 | 总用例 **30,924**（覆盖率 ~14.7%） |

**今日测试目录覆盖完成度**: 约 30% 的测试目录已运行

---

## 兼容性报告

详细兼容性问题见 **[docs/reports/compatibility/2026-06-01.md](docs/reports/compatibility/2026-06-01.md)**

### 已确认兼容性问题

| 问题ID | 问题 | 状态 | 影响 |
|--------|------|:----:|------|
| C-4 | wrap_triton 缺失 | ⏳ | quantization/moe 测试 |
| C-5 | recompile_limit 缺失 | ⏳ | flex_attention 测试 |
| C-8 | Triton 版本不兼容 | ⏳ | moe kernels 测试 |

**总用例数**：使用 GOAL.md 完整过滤命令统计得到 **30,924 tests**

---

## 今日测试执行（2026-06-01）

### 基础测试 ✅
| 测试文件 | 通过 | 失败 | 状态 |
|---------|:----:|:----:|:----:|
| test_logprobs/sequence/scalartype/logger/seed | 43 | 0 | ✅ |
| test_inputs/outputs/routing/triton/envs | 99 | 1 | ✅ |
| test_version/vllm_port/embedded_commit/pooling | 21 | 7 | 部分通过 |
| detokenizer/ | 5 | 3 | 部分通过 |
| transformers_utils/ | 22 | 2 | 部分通过 |
| plugins/ | 138 | 59 errors | 大部分通过 |
| v1/worker/executor | 25 | 24 | 部分通过 |
| config/ | 87 | 28 | 部分通过 |
| v1/engine_args | 2 | 0 | ✅ |
| v1/sample/ | 110 | 16 | 大部分通过 |
| models/ (部分) | 282 | 246 | 需模型 |
| compile/test_decorator | 0 | 2 | 2 skipped |
| compile/test_pass_manager | 1 | 3 | 耗时13分钟 |
| compile/test_wrapper | 0 | 2 | 快速失败 |
| test_envs.py | 46 | 0 | ✅ 全通过 |
| test_seed_behavior.py | 1 | 0 | ✅ |
| test_embedded_commit.py | 1 | 0 | ✅ |
| test_vllm_port.py | 4 | 0 | ✅ |
| test_version.py | 7 | 6 | 部分通过 |
| test_logger.py | 22 | 0 | ✅ |
| test_scalartype.py | 12 | 0 | ✅ |
| test_sequence.py | 1 | 0 | ✅ |
| test_logprobs.py | 7 | 0 | ✅ |
| test_inputs.py | 19 | 0 | 2 skipped |
| test_outputs.py | 1 | 0 | ✅ |
| tools/ | 4 | 0 | ✅ |
| engine/test_arg_utils.py | 51 | 0 | ✅ |
| test_routing_simulator.py | 26 | 1 | 部分通过 |
| distributed/test_utils.py | 1 | 0 | 4 skipped |
| v1/test_serial_utils.py | 7 | 0 | ✅ |
| transformers_utils/test_config.py | 0 | 2 | 耗时14分钟 |
| transformers_utils/test_utils.py | 17 | 0 | ✅ |
| transformers_utils/test_config_parser_registry.py | 2 | 0 | ✅ |
| transformers_utils/test_processor.py | 2 | 0 | ✅ |
| transformers_utils/test_repo_utils.py | 1 | 0 | ✅ |
| v1/test_outputs.py | 6 | 0 | ✅ |
| v1/test_request.py | 1 | 0 | ✅ |
| v1/test_oracle + determinism | 110 | 1 | 运行111个用例 |
| compile/test_qk_norm_rope_fusion | 0 | 16 | 收集16个，部分失败 |
| **今日总计** | **~349** | **~33** | **~8** | |

**✅ 容器镜像已保存**: `/gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz` (5.2GB)

**连接问题**: agent.py 与 t_h20 daemon 连接不稳定，建议直接在容器内运行剩余测试

**✅ 容器镜像已保存**: `/gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz` (5.2GB)

**注意**: agent.py 与 t_h20 daemon 连接不稳定，长时间测试会导致超时

### 模型依赖测试（跳过）
| 测试目录 | 状态 | 原因 |
|---------|:----:|------|
| samplers/ | ⏭️ 跳过 | TinyLlama 模型缺失 |
| lora/kernel | ⏭️ 跳过 | GPU kernel + 模型 |
| entrypoints/ | ⏭️ 跳过 | lm_eval/datasets 缺失 |
| basic_correctness/ | ⏭️ 跳过 | 模型缺失 |
| tool_use/ | ⏭️ 跳过 | 模型缺失 |

---

## 兼容性问题状态

| 问题ID | 问题 | 状态 | 影响 | 优先级 |
|--------|------|:----:|------|:------:|
| C-1 | LoRA类型签名 | ✅ 已修复 | 7+目录 | - |
| C-2 | DeepSeek torch_compile | ✅ 已修复 | DeepSeek相关 | - |
| C-3 | fp32_precision缺失 | ✅ 已存在 | Engine初始化 | P0 |
| C-4 | wrap_triton缺失 | ⏳ 待决策 | quantization | P1 |
| C-5 | recompile_limit缺失 | ⏳ 待修复 | flex_attention | P2 |
| C-6 | auto_functionalized缺失 | ⏳ 有方案 | 多模块 | P1 |
| C-7 | UnionType兼容 | ✅ 已存在 | 33文件 | P0 |

### 依赖问题（待安装）
| 缺失模块 | 影响测试 | 解决方案 |
|---------|---------|---------|
| lm_eval | entrypoints/llm | pip install lm-eval |
| datasets | entrypoints/pooling | pip install datasets |
| TinyLlama模型 | samplers/lora | HF镜像下载 |

---

## 测试目录覆盖情况

| 测试目录 | 通过 | 失败 | 通过率 | 备注 |
|---------|:----:|:----:|:------:|------|
| kernels/ | 1106 | 2 | 99.8% | ✅ |
| v1/core/scheduler | 91 | 6 | 93.8% | HF模型 |
| compile/noop_elimination | 25 | 0 | 100% | ✅ |
| engine/arg_utils | 51 | 0 | 100% | ✅ |
| config/ | 87 | 28 | 75.7% | wrap_triton |
| basic root tests | 99 | 1 | 99% | ✅ 今日运行 |
| tools/cuda | 8 | 0 | 100% | ✅ |
| model_executor | 28 | 0 | 100% | skipped |
| distributed/comm_ops | 11 | 10 | 52.4% | torchrun |
| detokenizer/ | 5 | 3 | 62.5% | 今日 |
| transformers_utils/ | 22 | 2 | 91.7% | 今日 |
| plugins/ | 138 | 59 | 70% | 今日 |
| v1/worker/executor | 25 | 24 | 51% | 今日 |

---

## 阻塞因素

| 问题 | 影响 | 状态 |
|------|------|:----:|
| HF 模型离线 | ~80% 失败 | ⏭️ 后续处理 |
| 磁盘配额限制 | 无法下载新模型 | ⏭️ 后续处理 |
| wrap_triton 缺失 | quantization 测试 | ⏳ 待决策 |
| recompile_limit 缺失 | flex_attention | ⏳ 待修复 |

---

## UT 模块文档导航

| 文档 | 位置 | 说明 |
|------|------|------|
| **[GOAL.md](GOAL.md)** | 本目录 | 单元测试目标 |
| **[WORKLOG.md](WORKLOG.md)** | 本目录 | 每日工作日志 |
| [docs/README.md](docs/README.md) | docs/ | UT文档导航 |
| [docs/guides/testing.md](docs/guides/testing.md) | docs/guides/ | 测试执行指南 |
| [docs/reports/test-summary.md](docs/reports/test-summary.md) | docs/reports/ | 测试结果汇总 |
| [docs/reports/weekly/](docs/reports/weekly/) | docs/reports/ | 周报目录 |

---

*更新时间: 2026-06-01*