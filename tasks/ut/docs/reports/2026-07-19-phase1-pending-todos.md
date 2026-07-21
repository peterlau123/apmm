# Phase 1 待办项清单（来自运行总结与事故复盘）

**生成时间**: 2026-07-19
**关联 Run**: `ut-20260718-164107`（Phase 1，已 100% 处理）
**文档性质**: 待办项汇总（Phase 2 执行前清单 + 防回归措施）

---

## 来源文档

本清单由以下两份文档总结分析得出：

| 来源文档 | 路径 | 贡献内容 |
|---------|------|---------|
| Phase 1 运行总结报告 | [`2026-07-19-phase1-500batch-run-summary.md`](2026-07-19-phase1-500batch-run-summary.md) | 失败/错误/超时测试分布、Phase 2 处理优先级（§9.1）、效率优化建议（§9.2）、bug 提交状态（§9.3） |
| generate_batch 装填率事故复盘 | [`../incidents/2026-07-19-generate-batch-normal-starvation-incident.md`](../incidents/2026-07-19-generate-batch-normal-starvation-incident.md) | 装填率根因、治本/治标方案（A/B2/B3）、防回归措施（监控 + 单测） |

> **验证**: 9 个 bug 修复 + 3 源码文件（generate_batch.py、execute_batch.py、auto_run_batches_two_phase.py）已 commit 在 `4154db4`，当前工作区干净（`git diff` 无未提交改动）。事故文档中的方案 A/B2/B3 均已标记 ✅ 已应用。

---

## ✅ 已完成（无需再处理）

| # | 事项 | 验证 |
|---|------|------|
| 1 | `create_batch_id()` 多 `_{index:04d}` 后缀违反 schema | 1384 batch ID 全合法 ✓ |
| 2 | Windows GBK 编码崩 ✓/✗ 符号（`PYTHONUTF8=1`） | 25h 无编码崩溃 ✓ |
| 3 | `torchrun python3 -m pytest` 误把 python3 当脚本 | distributed 测试能跑 ✓ |
| 4 | manifest 与 vllm 代码不同步（FP8->NVFP4） | 无 stale 节点 ✓ |
| 5 | pi auto-checkpoint 回退 git-tracked 编辑（禁用扩展 + skip-worktree） | 修复持久 ✓ |
| 6 | GPU 空闲判定看利用率不看显存 -> OOM（改显存占用比 < 50%） | GPU 0 正确排除 ✓ |
| 7 | manifest 状态冻结致重复选已跑过的（改从 test_load 选） | 重复选中 378->0 ✓ |
| 8 | normal 候选不足丢弃 distributed 致装填率 25%（`len(normal)>=batch_size` 降级） | 装填率 2.4->8.0 ✓ |
| 9 | normal 不足且无 distributed 抛 ValueError（`or not distributed` 回退） | 最后 3 pending 跑完 ✓ |

**Phase 1 最终结果**: 1384 batch / 99.71% 成功率 / test_load 4000 100% 处理 / 通过率 94.0%。

---

## 🔲 待办项

### 一、Phase 2 执行前必须处理（优先级 🔴）

| # | 事项 | 来源 | 说明 | 涉及文件/位置 |
|---|------|------|------|--------------|
| P1-1 | **跳过 HF 网络测试**：离线环境下联网测试必失败，在 filter_rules 中排除 | 总结 §9.2 | 最快见效，避免 Phase 2 无效重跑 | `skills/ut/ut_common/filter_rules.yaml` |
| P1-2 | **提高 wall_timeout**：distributed e2e 测试 300s 不够，提至 600-900s | 总结 §4.3, §9.2 | 参数改一行，distributed 测试不再批量超时 | `tasks/ut/deployment/production/config/workflow.yaml`（生产）/ 策略配置 |
| P1-3 | **failed 重新分类**：91 个 `assertion` 实为 HuggingFace 网络错误，重分类为 `network`/`download_error` | 总结 §4.1, §9.1 | 先分类再决定是否重试，区分真断言失败 vs 环境失败 | error_type 分类逻辑（execute_batch / 失败处理 skill） |
| P1-4 | **error 排查**：12 个 `tests/entrypoints/openai/` collection 错误，排查缺失依赖或模块变更 | 总结 §4.2, §9.1 | 可能 import 路径变更或依赖未安装 | `tests/entrypoints/openai/test_translation_validation.py`（5）、`test_response_api_parsable_context.py`（4）、`test_response_api_simple.py`（3） |
| P1-5 | **ignored 重跑**：2479 个超时/无结果测试，提高 wall_timeout 后重试 | 总结 §4.3, §9.1 | ~1500 个「JUnit XML no testcase」+ ~980 个 SIGKILL 超时 | Phase 2 策略：重置 ignored -> pending |

### 二、防回归措施（代码/监控/测试，优先级 🟡）

| # | 事项 | 来源 | 说明 | 涉及文件/位置 |
|---|------|------|------|--------------|
| D1-1 | **监控：tests_per_batch < batch_size 时告警** | 事故 §防回归 | 装填率下降时第一时间感知 | batch 生成后校验逻辑（generate_batch / auto_run_batches_two_phase） |
| D1-2 | **监控：重复选中率告警**（同一 test_node 被 >1 个 batch 选中 = 异常） | 事故 §防回归 | 选择源脱节的信号 | 选择端逻辑（generate_batch） |
| D1-3 | **单测：manifest 冻结场景验证** | 事故 §防回归 | 构造 manifest 不更新 + generate_batch 从 manifest 选的场景，验证不重复选 | `tests/ut/`（新建单测） |

### 三、环境准备（优先级 🟡）

| # | 事项 | 来源 | 说明 |
|---|------|------|------|
| E1-1 | **检查 HF 模型缓存完整性** | 总结 §4.1 | Phase 2 前确认 HF 模型已离线缓存，减少因网络下载导致的超时/failed（尽管 `HF_HUB_OFFLINE=1`，部分测试仍尝试联网） |

---

## 优先级排序建议

**Phase 2 前必须做（#P1-1 ~ #P1-5）**：核心是排除 HF 联网测试 + 提高 wall_timeout + 重新分类 failed，否则 Phase 2 会重现同样的失败模式。

1. 🔴 **P1-1** filter_rules 排除 HF 联网测试 — 最快见效，改一个 yaml
2. 🔴 **P1-2** wall_timeout 300s -> 600s — 参数改一行，distributed 不再超时
3. 🟡 **P1-3** failed 重新分类 — 数据准确性，区分真失败 vs 环境失败
4. 🟡 **P1-4** error 排查 — 12 个 collection 错误需依赖检查
5. 🟡 **P1-5** ignored 重跑 — 依赖 P1-2 完成
6. 🟡 **E1-1** 模型缓存检查 — 环境准备
7. 🟡 **D1-1 ~ D1-3** 防回归监控 + 单测 — 确保装填率和选择源长期可靠

---

## 相关文件索引

| 类别 | 文件 | 说明 |
|------|------|------|
| 来源 - 总结报告 | `tasks/ut/docs/reports/2026-07-19-phase1-500batch-run-summary.md` | Phase 1 运行总结 |
| 来源 - 事故复盘 | `tasks/ut/docs/incidents/2026-07-19-generate-batch-normal-starvation-incident.md` | 装填率事故根因 + 修复 |
| 来源 - 启动 bug 复盘 | `tasks/ut/docs/incidents/2026-07-18-phase1-startup-bugs-and-auto-checkpoint-rollback.md` | bug 1-6 详情 |
| 修复 commit | `4154db4` | `fix(ut): Phase 1 启动连环 bug 修复 + generate_batch 装填率优化` |
| 待改 - 过滤规则 | `skills/ut/ut_common/filter_rules.yaml` | P1-1 排除 HF 联网测试 |
| 待改 - workflow 配置 | `tasks/ut/deployment/production/config/workflow.yaml` | P1-2 wall_timeout |
| 待改 - generate_batch | `skills/ut/batch-selector/scripts/generate_batch.py` | D1-1/D1-2 监控点 |
| 待改 - execute_batch | `skills/ut/unit-test-executor/scripts/execute_batch.py` | P1-3 error_type 分类 |
| 待改 - 两阶段调度 | `tasks/ut/scripts/auto_run_batches_two_phase.py` | D1-1 装填率校验 |
| run 数据 | `runs/ut-20260718-164107/` | Phase 1 数据（4000 测试结果） |
