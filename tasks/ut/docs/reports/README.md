# UT Reports — 测试报告 / 每周兼容性检查报告

> 本目录存放 UT workflow 的报告文档（2026-08-06 重组）：
> - **测试运行报告** — 单次 run 的问题总结与修复记录（`reports/*.md`）
> - **每周兼容性检查报告** — 每周五输出，聚焦 vLLM 0.13.0 + torch 2.5.1 兼容性问题（`reports/weekly/*.md`）
> - **导出文件** — 报告 PDF 导出（`reports/release/`）
> - **历史归档** — 旧版 compatibility/weekly（`reports/archive/`）

---

## 测试运行报告

| 报告 | 日期 | 说明 |
|------|------|------|
| [2026-06-24-L4-test-issues-and-fixes.md](2026-06-24-L4-test-issues-and-fixes.md) | 2026-06-24 | L4 测试运行问题总结：PYTHONPATH 泄漏、依赖链 race condition、Watchdog 超时 |
| [2026-07-19-phase1-500batch-run-summary.md](2026-07-19-phase1-500batch-run-summary.md) | 2026-07-19 | Phase 1 首轮 500 batch 全量执行：1213 测试已处理，通过率 92.9%，6 bug 修复 |
| [2026-07-19-phase1-pending-todos.md](2026-07-19-phase1-pending-todos.md) | 2026-07-19 | Phase 1 待办项清单：Phase 2 前必做项 + 防回归措施 |
| [2026-08-04-phase2-timeout-retry-fixes-and-resume.md](2026-08-04-phase2-timeout-retry-fixes-and-resume.md) | 2026-08-04 | Phase 2 timeout 重试 3+1 bug 修复 + 动态并行度 + 全量重试恢复 |
| [2026-08-05-phase2-full-retry-summary.md](2026-08-05-phase2-full-retry-summary.md) | 2026-08-05 | Phase 2 全量重试完成：passed 1418→2723（68%），剩余 ignored 完整分类 |
| [2026-08-05-phase2-retry-final-summary.md](2026-08-05-phase2-retry-final-summary.md) | 2026-08-05 | **Phase 2 重跑最终总结**：三轮重跑，passed 1418→3444（86.1%），4 个问题全部解决 |
| [2026-08-06-vllm-0.13.0-torch2.5.1-8000cases-compat-issues.md](2026-08-06-vllm-0.13.0-torch2.5.1-8000cases-compat-issues.md) | 2026-08-06 | **8000 cases run 兼容性问题**：4233 passed（52.9%）/ 3767 failed，`_moe_C` 注册失效 2638 + FP8/inductor/DeepGEMM 清单 |
| [2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md](2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md) | 2026-08-05 | vLLM 0.13.0 + torch 2.5.1 在 H20 兼容性问题全清单（6 项，含解决状态与原因剖析） |

---

## 每周兼容性检查报告（weekly/）

> 每周五 17:00 自动生成，聚焦 **vLLM 0.13.0 + torch 2.5.1** 兼容性问题。
> 模板：**相对上周的增量发现** + 本周 reports/incidents + ut_logs 入库增量 + 问题清单。

| 报告 | 日期 | 说明 |
|------|------|------|
| （待首次生成） | — | — |

---

## 导出文件（release/）

| 源报告 | 导出文件 | 说明 |
|--------|---------|------|
| — | — | （暂无，见 [release/README.md](release/README.md)） |

---

## 历史归档（archive/）

旧版 compatibility/weekly 报告（2026-05 ~ 06）已归档至 [archive/](archive/)，不再更新。

---

## 归档规范

- 运行报告命名：`YYYY-MM-DD-{topic}.md`，每份含：问题描述、修复方案、待优化项、相关文件引用
- **每周兼容性检查报告**命名：`weekly/YYYY-MM-DD-compat-check.md`（周五自动生成）
- 报告生成后同步更新本索引 + `tasks/ut/README.md`

*更新时间: 2026-08-06*
