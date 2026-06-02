# 单元测试整体目标

> **完成过滤后的所有 pytest 测试，修复问题并提交至 vLLM**

---

## 测试环境

> **重要：单元测试必须在 t_h20 (10.10.154.13) 上完成，不是 ascend 机器**

| 服务器 | IP | 用途 | 说明 |
|--------|-----|------|------|
| **t_h20** | 10.10.154.13 | **单元测试执行** | H20-3e GPU，运行 pytest |
| t_ascend | 10.250.121.21 | 联网下载 | 下载模型、依赖包 |
| 堡垒机 | 10.10.192.55:22 | SSH网关 | 需要双密码认证 |

### 测试容器

| 容器名 | 镜像 | 版本信息 |
|--------|------|---------|
| `v0.13.0_torch2.5.1_compile` | `vllm/vllm-openai:v0.13.0` | vLLM 0.13.0 + torch 2.5.1+cu124 |

### 容器镜像备份要求

完成单元测试后，需将 h20 上的测试容器保存到共享存储：

```bash
# 在 t_h20 上执行 - 将容器 commit 为镜像后保存
sudo docker commit v0.13.0_torch2.5.1_compile v0.13.0_torch2.5.1_compile_backup:latest
sudo docker save v0.13.0_torch2.5.1_compile_backup:latest | gzip > /gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz
```

**备份位置**: `/gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz`

**说明**: 使用 `docker commit` 保存容器当前状态（包含可能的配置变更），而非原始 `vllm/vllm-openai:v0.13.0` 镜像

---

## 测试范围

### 过滤命令

```bash
pytest tests/ --collect-only \
    --ignore-glob="tests/**/*rocm*" \
    --ignore-glob="tests/**/*tpu*" \
    --ignore-glob="tests/**/multimodal*" \
    --ignore-glob="tests/**/nixl*" \
    --ignore-glob="tests/**/ec_connector*" \
    --ignore-glob="tests/**/*image*.py" \
    --ignore-glob="tests/**/*video*.py" \
    --ignore-glob="tests/**/*audio*" \
    --ignore-glob="tests/**/encoder*" \
    --ignore-glob="tests/**/prithvi*" \
    --ignore-glob="tests/models/language/generation/test_gemma.py" \
    --ignore-glob="tests/models/language/generation/test_granite.py" \
    --ignore-glob="tests/models/language/generation/test_hybrid.py" \
    --ignore-glob="tests/models/language/generation/test_mistral.py" \
    --ignore-glob="tests/models/language/generation/test_phimoe.py" \
    --ignore-glob="tests/models/language/generation_ppl_test/test_gemma.py" \
    --ignore-glob="tests/models/language/generation_ppl_test/test_gpt.py" \
    --ignore-glob="tests/models/language/generation_ppl_test/test_qwen.py" \
    --ignore-glob="tests/models/language/pooling_mteb_test/*" \
    --ignore-glob="tests/models/language/pooling/*" \
    --ignore-glob="tests/reasoning/test_deepseekr1_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_deepseekv3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_ernie45_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_glm4_moe_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_gptoss_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_granite_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_holo2_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_hunyuan_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_mistral_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_olmo3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_qwen3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_seedoss_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_base_thinking_reasoning_parser.py" \
    -q 2>&1 | tail -30
```

### 排除说明

| 排除类别 | 原因 |
|---------|------|
| `rocm*` | AMD GPU 平台，非测试目标 |
| `tpu*` | TPU 平台，非测试目标 |
| `multimodal*` | 多模态功能，暂不支持 |
| `nixl*` | NVIDIA 传输库，环境依赖 |
| `ec_connector*` | 外部连接器，环境依赖 |
| `*image/video/audio*` | 多模态相关 |
| `encoder*` | 编码器相关 |
| `prithvi*` | 地理模型，非目标 |
| `generation/test_*` | 特定模型生成测试 |
| `generation_ppl_test/*` | PPL 测试需模型权重 |
| `pooling_mteb_test/*` | MTEB 基准，需额外依赖 |
| `pooling/*` | Embedding 模型测试 |
| `reasoning/test_*` | 推理模型解析器，需特定模型 |

---

## 任务目标

### 1. 修复问题并提交至 vLLM

- 发现代码 bug 后，在 vLLM 源码中修复
- 提交 commit 到 `/gpfs/gcsp/M2.7_verify/vllm/`
- 记录修复内容、commit hash、影响范围

### 2. 记录问题并分类

问题分类框架：

| 类别 | 说明 | 示例 |
|------|------|------|
| **C-代码Bug** | vLLM 源码缺陷 | 类型签名错误、逻辑错误 |
| **E-环境问题** | 测试环境限制 | HF 离线、磁盘配额、GPU 内存 |
| **D-依赖缺失** | Python 包缺失 | mteb, multiprocess, grpc |
| **P-平台兼容** | PyTorch API 缺失 | fp32_precision, wrap_triton |
| **M-模型缺失** | HuggingFace 模型未下载 | Llama, Snowflake 等 |
| **S-跳过问题** | 合理跳过的测试 | 平台不支持、功能未启用 |

### 3. 输出整体统计报告

最终报告内容：

```
## 测试统计
- 总用例数: N
- 通过: X (通过率 Y%)
- 失败: F
- 跳过: S
- 错误: E

## 问题分类统计
| 类别 | 数量 | 说明 |
|------|------|------|

## vLLM 修复提交
| Commit | 日期 | 修复内容 | PR状态 |
|--------|------|---------|--------|

## 未解决问题
| 问题ID | 描述 | 状态 | 原因 |
|--------|------|:------:|------|
```

---

## 完成标准

当以下条件全部满足时，任务完成：

1. ✅ 所有过滤后的测试目录已执行
2. ✅ 所有代码 bug 已修复并提交
3. ✅ 问题分类记录完整
4. ✅ 整体统计报告已输出
5. ✅ 未解决问题有明确说明

---

## 进度检查

每次完成阶段性任务后，阅读此文件检查：

- [ ] 测试覆盖率达标？（目标：所有过滤后目录）
- [ ] 代码修复已提交？
- [ ] 问题分类已记录？
- [ ] 统计报告已生成？

---

## 相关文档

- [PROGRESS.md](PROGRESS.md) - 实时进度
- [docs/reports/test-summary.md](docs/reports/test-summary.md) - 测试结果
- [docs/reports/error-analysis.md](docs/reports/error-analysis.md) - 错误分析
- [docs/guides/testing.md](docs/guides/testing.md) - 执行指南

---

*创建时间: 2026-06-01*
