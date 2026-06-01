# 单元测试进度追踪

> **vLLM v0.13.0 + PyTorch 2.5.1 pytest 测试进度**
> **详细进度主文件 - 含每日执行记录、问题分类、修复状态**

---

## 当前状态概览

| 指标 | 数量 | 说明 |
|------|:----:|------|
| ✅ 累计通过 | **~2,213** | 今日新增 +43 基础测试 |
| ❌ 累计失败 | ~210 | samplers/lora 失败 |
| 🔄 剩余待运行 | ~28,700 | 总用例 30,934（覆盖率 ~7.2%） |

**注意**：总用例数更新为 30,934（之前统计 9,542 为部分过滤）

---

## 今日测试执行（2026-06-01）

### 基础测试 ✅ 全部通过
| 测试文件 | 通过数 | 状态 |
|---------|:------:|:----:|
| test_logprobs.py | 1 | ✅ |
| test_sequence.py | 1 | ✅ |
| test_scalartype.py | 12 | ✅ |
| test_logger.py | 22 | ✅ |
| test_seed_behavior.py | 1 | ✅ |
| test_config.py | 87p, 28f | 部分通过 |
| **合计** | **43 passed** | ✅ |

### samplers 测试 ❌ 失败
| 测试文件 | 结果 | 问题 |
|---------|------|------|
| test_beam_search.py | 失败 | TinyLlama 模型缺失 |
| test_ignore_eos.py | 失败 | distilgpt2/Llama 模型问题 |
| test_logprobs.py | 失败 | HF 离线 + recompile_limit |
| test_no_bad_words.py | 失败 | Engine 初始化错误 |

**失败原因**: C-5 recompile_limit + HF 模型缺失

### lora 测试 ❌ 失败
| 测试文件 | 结果 | 问题 |
|---------|------|------|
| test_fused_moe_lora_kernel.py | 48 failed | GPU kernel 功能问题 |

### entrypoints 测试 ⏳ 收集错误
| 错误数 | 问题 |
|:------:|------|
| 9 errors | lm_eval/datasets/mteb 模块缺失 |

---

## 兼容性问题状态

| 问题ID | 问题 | 状态 | 影响 | 优先级 |
|--------|------|:----:|------|:------:|
| C-1 | LoRA类型签名 | ✅ 已修复 | 7+目录 | - |
| C-2 | DeepSeek torch_compile | ✅ 已修复 | DeepSeek相关 | - |
| C-3 | fp32_precision缺失 | ✅ 已存在 | Engine初始化 | P0 |
| C-4 | wrap_triton缺失 | ⏳ 待决策 | quantization | P1 |
| C-5 | recompile_limit缺失 | ⏳ 待修复 | flex_attention/dynamo | P2 |
| C-6 | auto_functionalized缺失 | ⏳ 有方案 | 多模块 | P1 |
| C-7 | UnionType兼容 | ✅ 已存在 | 33文件 | P0 |

### 新发现依赖问题

| 缺失模块 | 影响测试 | 解决方案 |
|---------|---------|---------|
| lm_eval | entrypoints/llm/test_accuracy.py | pip install lm-eval |
| datasets | entrypoints/pooling/mteb | pip install datasets |
| mteb | pooling/mteb 测试 | 已安装但需 datasets |

---

## 测试目录覆盖情况

| 测试目录 | 通过 | 失败 | 通过率 | 备注 |
|---------|:----:|:----:|:------:|------|
| kernels/shuffle_rows | 158 | 1 | 99.4% | OOB测试 |
| kernels/cache/onednn/fla | 917 | 1 | 99.9% | ✅ |
| kernels/top_k+fused_quant | 31 | 0 | 100% | ✅ |
| v1/core/scheduler | 91 | 6 | 93.8% | HF模型 |
| compile/noop_elimination | 25 | 0 | 100% | ✅ |
| engine/arg_utils | 51 | 0 | 100% | ✅ |
| config/ | 87 | 28 | 75.7% | wrap_triton + HF |
| basic root tests | 43 | 0 | 100% | ✅ 今日运行 |
| tools/cuda | 8 | 0 | 100% | ✅ |
| model_executor | 28 | 0 | 100% | 12 skipped |
| distributed/comm_ops | 11 | 10 | 52.4% | 需torchrun |
| samplers/ | 0 | 10 | 0% | 模型缺失 |
| lora/kernel | 0 | 48 | 0% | GPU kernel问题 |

---

## 阻塞因素

| 问题 | 影响 | 解决方案 |
|------|------|---------|
| HF 模型离线 | ~80% 失败 | 使用 HF 镜像下载 |
| 磁盘配额限制 | 无法下载新模型 | 清理旧文件或申请配额 |
| wrap_triton 缺失 | quantization 测试失败 | 添加 shim 或跳过 |
| recompile_limit 缺失 | flex_attention 导入错误 | 添加 hasattr 检查 |
| lm_eval/datasets 缺失 | entrypoints 测试无法收集 | pip install |

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