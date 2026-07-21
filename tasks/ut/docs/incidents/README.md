# 事故复盘 Incident Post-mortems

> 已发生事故的完整复盘文档。每条记录至少包含：**触发条件、根因、证据链、修复动作、防回归措施**。
> 新 incident 落档时同步更新本索引 + 在 `docs/README.md` 主导航的"事故复盘"区段加链接。

## 索引

| 日期 | 标题 | 影响范围 | 状态 |
|---|---|---|---|
| 2026-06-22 | [L4 测试 Stage-3 Fabrication 事故 (run `ut-20260621-234651`)](2026-06-22-l4-fabrication.md) | UT Kanban worker 链路（executor/fixer），ai-engineer Feishu 群被注入伪造完成报告 | ✅ 已闭环 |
| 2026-06-23 | [L4 PASS 后的 3 项产品问题复盘与修复设计 (run `ut-20260623-105441`)](2026-06-23-l4-postmortem-and-fixes.md) | Intent 分类 / Bastion OTP 自动化 / fixer→resolver 断链 | 📐 设计阶段 |
| 2026-07-18 | [Phase 1 启动连环 bug + pi auto-checkpoint 回退事故 (run `ut-20260718-164107`)](2026-07-18-phase1-startup-bugs-and-auto-checkpoint-rollback.md) | auto-checkpoint stash 回退 / batch_id schema / GBK 编码 / torchrun 命令 / manifest 失效 | ✅ 已闭环 |
| 2026-07-19 | [generate_batch 批次装填率过低事故（manifest 状态冻结）](2026-07-19-generate-batch-normal-starvation-incident.md) | Phase 1 batch 装填率仅 25%，manifest 状态冻结导致重复选 + normal 候选不足 | 📐 待修复 |
| 2026-07-19 | [triton 3.5.0 与 torch 2.5.1 版本冲突事故（vllm vs inductor）](2026-07-19-triton-torch-version-conflict-incident.md) | 19 个 test_fusion_attn 恒定 failed，vllm 需 triton 3.5.0 / torch 2.5.1 需 triton 3.1.0，依赖冲突 | 📐 待评估 |
| 2026-07-19 | [flashmla FP8 kernel 在 H20 上输出错误事故（C++ 扩展非 triton）](2026-07-19-flashmla-fp8-h20-incorrect-output-incident.md) | 48 个 test_flashmla FP8 参数化恒定 failed，_flashmla_extension_C 的 FP8 kernel 在 H20 部分位置输出错误大值/nan，平台兼容问题 | 📐 待排查 |
| 2026-07-19 | [HF 模型缓存缺失事故（16 个 failed，3 个模型未离线缓存）](2026-07-19-hf-model-cache-missing-incident.md) | 16 个测试因 HF 模型未缓存失败，涉及 TinyLlama/meta-llama/hmellor 3 模型 | ✅ 已修复 |

## 相关入口

- 主导航：[`docs/README.md`](../README.md)
- vLLM 远端修复操作指南：[`tasks/ut/docs/guides/troubleshooting.md`](../guides/troubleshooting.md)
- UT supervisor 通道契约：[`skills/ut/hermes-workflow/SKILL.md`](../../skills/ut/hermes-workflow/SKILL.md)（§11 Pitfalls 是本目录事故沉淀的代码侧落点）
- UT worker 硬契约：[`skills/ut/unit-test-executor/SKILL.md`](../../skills/ut/unit-test-executor/SKILL.md) §禁止操作、[`skills/ut/failure-handler/SKILL.md`](../../skills/ut/failure-handler/SKILL.md) §禁止操作
