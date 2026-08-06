# UT Reports — 测试报告 / 周报 / 兼容性分析

本目录存放 UT workflow 的各类报告文档：

- **测试运行报告** — 单次测试运行的问题总结与修复记录
- **周报** — UT 验证进度周报
- **兼容性分析** — MACA/H20 硬件兼容性分析报告

---

## 测试运行报告

| 报告 | 日期 | 说明 |
|------|------|------|
| [2026-06-24-L4-test-issues-and-fixes.md](2026-06-24-L4-test-issues-and-fixes.md) | 2026-06-24 | L4 测试运行问题总结：PYTHONPATH 泄漏、依赖链 race condition、Watchdog 超时 |
| [2026-07-19-phase1-500batch-run-summary.md](2026-07-19-phase1-500batch-run-summary.md) | 2026-07-19 | Phase 1 首轮 500 batch 全量执行：1213 测试已处理，通过率 92.9%，6 bug 修复 |
| [2026-07-19-phase1-pending-todos.md](2026-07-19-phase1-pending-todos.md) | 2026-07-19 | Phase 1 待办项清单：Phase 2 前必做项（filter_rules/wall_timeout/failed分类）+ 防回归措施 |
| [2026-08-04-phase2-timeout-retry-fixes-and-resume.md](2026-08-04-phase2-timeout-retry-fixes-and-resume.md) | 2026-08-04 | Phase 2 timeout 重试 3+1 bug 修复（旧结果残留/反斜杠路径/不回写 test_load/container_env 丢失）+ 动态并行度 + 全量重试恢复 |
| [2026-08-05-phase2-full-retry-summary.md](2026-08-05-phase2-full-retry-summary.md) | 2026-08-05 | Phase 2 全量重试完成：727 timeout batch / 440 super batches，passed 1418→2723（68%），剩余 ignored 完整分类 |
| [2026-08-05-phase2-retry-final-summary.md](2026-08-05-phase2-retry-final-summary.md) | 2026-08-05 | **Phase 2 重跑最终总结**：三轮重跑（全量/kernel/fql device 映射），passed 1418→3444（86.1%），4 个问题全部解决 |

---

## 周报

（待补充）

---

## 兼容性分析

| 报告 | 日期 | 说明 |
|------|------|------|
| [2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md](2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md) | 2026-08-05 | vLLM 0.13.0 + torch 2.5.1 在 H20 兼容性问题：illegal memory access（403）/ CUDA_VISIBLE_DEVICES 参数化 not found（559）/ server 启动超时 / torch.compile 20min+ |

---

## 归档规范

- 报告文件命名格式：`YYYY-MM-DD-{topic}.md`
- 每份报告应包含：问题描述、修复方案、待优化项、相关文件引用
- 报告生成后应在 `tasks/ut/README.md` 的"故障复盘 / 历史 incident"行或"周报 / 兼容性分析"行添加引用

---

*更新时间: 2026-06-24*