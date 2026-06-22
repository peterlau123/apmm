# 单元测试整体目标

> **完成过滤后的所有 pytest 测试，修复问题并提交至 vLLM**

---

## 目录

- [测试环境](#测试环境)
- [测试范围](#测试范围)
- [任务目标](#任务目标)
- [测试统计](#测试统计)
- [问题分类统计](#问题分类统计)
- [修复提交记录](#修复提交记录)
- [未解决问题](#未解决问题)
- [完成标准](#完成标准)
- [进度检查](#进度检查)
- [相关文档](#相关文档)

---

## 测试环境

单元测试必须在 **t_h20 (10.10.154.13)** 上完成。详见 [docs/guides/environment.md](../../docs/guides/environment.md)。

| 容器名 | 镜像 | 版本信息 |
|--------|------|---------|
| `v0.13.0_torch2.5.1_compile` | `vllm/vllm-openai:v0.13.0` | vLLM 0.13.0 + torch 2.5.1+cu124 |

### 容器镜像备份

完成后将容器保存到共享存储：

```bash
sudo docker commit v0.13.0_torch2.5.1_compile v0.13.0_torch2.5.1_compile_backup:latest
sudo docker save v0.13.0_torch2.5.1_compile_backup:latest | gzip > /gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz
```

**备份位置**: `/gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile.tar.gz`

---

## 测试范围

测试过滤规则详见 [skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml)。

`test_manifest.json` 中包含各测试项的进展状态，请及时更新。

---

## 任务目标

### 1. 修复问题并提交至 vLLM

- 发现代码 bug 后，在 vLLM 源码中修复
- 提交 commit 到 `/gpfs/gcsp/M2.7_verify/vllm/`
- 记录修复内容、commit hash、影响范围

### 2. 记录问题并分类

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

## 修复提交记录
| Commit | 日期 | 修复内容 | PR状态 |

## 未解决问题
| 问题ID | 描述 | 状态 | 原因 |
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

- [ ] 测试覆盖率达标？（目标：所有过滤后目录）
- [ ] 代码修复已提交？
- [ ] 问题分类已记录？
- [ ] 统计报告已生成？

---

## 相关文档

- [PROGRESS.md](PROGRESS.md) - 实时进度
- [docs/reports/test-summary.md](../../docs/reports/test-summary.md) - 测试结果
- [docs/guides/testing.md](../../docs/guides/testing.md) - 执行指南

---

*创建时间: 2026-06-01 | 最后更新: 2026-06-12*
