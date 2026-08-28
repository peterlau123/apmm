# Phase 1 待办项清单（来自运行总结与事故复盘）

**生成时间**: 2026-07-19
**最近更新**: 2026-07-19（防回归 + 环境准备 + 文档修正完成）
**关联 Run**: `ut-20260718-164107`（Phase 1，已 100% 处理）
**文档性质**: 待办项汇总（Phase 2 执行前清单 + 防回归措施）

---

## 来源文档

本清单由以下文档总结分析得出：

| 来源文档 | 路径 | 贡献内容 |
|---------|------|---------|
| Phase 1 运行总结报告 | [`2026-07-19-phase1-500batch-run-summary.md`](2026-07-19-phase1-500batch-run-summary.md) | 失败/错误/超时测试分布、Phase 2 处理优先级（§9.1）、效率优化建议（§9.2）、bug 提交状态（§9.3） |
| generate_batch 装填率事故复盘 | [`../incidents/2026-07-19-generate-batch-normal-starvation-incident.md`](../incidents/2026-07-19-generate-batch-normal-starvation-incident.md) | 装填率根因、治本/治标方案（A/B2/B3）、防回归措施（监控 + 单测） |
| HF 模型缓存缺失事故 | [`../incidents/2026-07-19-hf-model-cache-missing-incident.md`](../incidents/2026-07-19-hf-model-cache-missing-incident.md) | 91 failed 精确分类、3 模型补齐、Phase 2 前缓存核对 |

> **验证**: 
> - 9 个 bug 修复 + 3 源码文件已 commit `4154db4`，方案 A/B2/B3 均已应用。
> - 防回归 D1-1/D1-2/D1-3 + HF 缓存预检 + 文档修正已 commit `cda6d7b`。

---

## ✅ 已完成（无需再处理）

### Phase 1 启动 bug（9 个，commit `4154db4`）

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

### Phase 2 前处理项（commit `cda6d7b` 及之前）

| # | 事项 | 验证 |
|---|------|------|
| P1-2 | **提高 wall_timeout** 300s -> 600s | workflow.yaml Stage 3 `timeout: 600` ✓ |
| P1-4 | **error 排查**（12 个 openai collection 错误） | 5 filter（`test_translation_validation.py`）+ 7 fix（Response API torch.compile+deep_gemm）✓ |
| Doc-1 | **summary §4.1 修正**：91 failed「多数 HF 网络错误」-> 精确分类 | 引用 incident 附录（HF16/triton19/flashmla48/server5/其他3）✓ |
| D1-1 | **监控：装填率告警**（tests_per_batch < batch_size 时 WARN） | `generate_batch.py` 生成后打印诊断 ✓ |
| D1-2 | **监控：重复选中告警**（同一 test_node 被 >1 batch 选中） | `auto_run_batches_two_phase.py` 维护 `seen_test_nodes` 检测 ✓ |
| D1-3 | **单测：manifest 冻结场景验证**（不重复选） | `test_generate_batch_v5.py` +3 测试，12 passed ✓ |
| E1-1 | **HF 模型缓存完整性检查** | 预检脚本 `check_hf_cache_refs.py` + 远端核对；3 已知缺失 + 5 新缺失模型全部补齐 ✓ |

**Phase 1 最终结果**: 1384 batch / 99.71% 成功率 / test_load 4000 100% 处理 / 通过率 94.0%。

**91 failed 精确分类**（手动，见 HF 缓存 incident 附录）：flashmla 数值断言 48 / triton 版本冲突 19 / HF 缓存缺失 16（已补齐）/ server 启动 5 / 其他 3。

---

## 🔲 待办项

> **备注**：以下剩余事项均由用户自行决定是否/何时处理，不强制。P1-5 为 Phase 2 执行动作（启动时自然发生），P1-1/P1-3 为可选项（可做可不做）。

### 一、Phase 2 执行前（优先级 🔴）

| # | 事项 | 状态 | 说明 |
|---|------|------|------|
| P1-5 | **ignored 2479 个重跑** | ❌ 待 Phase 2 启动 | Phase 2 执行动作（非独立开发项）。依赖 P1-2（已完成 600s）。启动时重置 ignored -> pending 重跑。~1500 个「JUnit XML no testcase」+ ~980 个 SIGKILL 超时 |

### 二、评估后无需做 / 可选（优先级 ⚪）

| # | 事项 | 状态 | 说明 |
|---|------|------|------|
| P1-1 | **filter_rules 排除 HF 联网测试** | ⚪ 评估后无需做 | 91 failed 里 HF 16 个全是模型缓存问题（已补齐），无「纯联网测试」类别。HF 缓存 incident 明确「模型下载已解决，无需 filter 排除」。**已被 E1-1 覆盖** |
| P1-3 | **error_type 自动分类逻辑** | ⚪ 可选 | 91 failed 已手动分类（incident 附录）。`execute_batch._error_type_from_message` 只识别 OOM，无 network/download_error 自动分类。若 Phase 2 后还要跑多轮，建议加自动分类免手动；若 Phase 2 是最后一轮，手动分类已够 |

---

## 优先级排序建议

1. 🔴 **P1-5** ignored 重跑 - Phase 2 启动时执行（P1-2 已完成，wall_timeout 600s 已生效）
2. ⚪ **P1-3** error_type 自动分类 - 可选，视是否多轮 run 而定
3. ~~P1-1~~ 已被 E1-1 覆盖，无需单独做

> 防回归（D1-1/D1-2/D1-3）+ 环境准备（E1-1）+ 文档修正（Doc-1）+ Phase 2 前处理（P1-2/P1-4）均已完成。Phase 2 启动仅需执行 P1-5（重跑 ignored）。

---

## 相关文件索引

| 类别 | 文件 | 说明 |
|------|------|------|
| 来源 - 总结报告 | `tasks/ut/docs/reports/2026-07-19-phase1-500batch-run-summary.md` | Phase 1 运行总结（§4.1 已修正） |
| 来源 - 装填率事故 | `tasks/ut/docs/incidents/2026-07-19-generate-batch-normal-starvation-incident.md` | 装填率事故根因 + 修复 |
| 来源 - HF 缓存事故 | `tasks/ut/docs/incidents/2026-07-19-hf-model-cache-missing-incident.md` | 91 failed 分类 + 缓存核对 |
| 来源 - 启动 bug 复盘 | `tasks/ut/docs/incidents/2026-07-18-phase1-startup-bugs-and-auto-checkpoint-rollback.md` | bug 1-6 详情 |
| 修复 commit | `4154db4` | `fix(ut): Phase 1 启动连环 bug 修复 + generate_batch 装填率优化` |
| 防回归 commit | `cda6d7b` | `fix(ut): 防回归措施 + 文档不一致修复 + HF 缓存预检` |
| 已改 - generate_batch | `skills/ut/batch-selector/scripts/generate_batch.py` | D1-1 装填率告警 |
| 已改 - 两阶段调度 | `tasks/ut/scripts/auto_run_batches_two_phase.py` | D1-2 重复选中告警 |
| 已改 - 单测 | `tests/ut/unit/test_generate_batch_v5.py` | D1-3 manifest 冻结单测 |
| 新增 - 预检脚本 | `tasks/ut/scripts/check_hf_cache_refs.py` | E1-1 HF 缓存引用预检 |
| 已改 - workflow 配置 | `tasks/ut/deployment/production/config/workflow.yaml` | P1-2 wall_timeout=600 |
| 待改（可选）- execute_batch | `skills/ut/unit-test-executor/scripts/execute_batch.py` | P1-3 error_type 自动分类（可选） |
| run 数据 | `runs/ut-20260718-164107/` | Phase 1 数据（4000 测试结果） |
