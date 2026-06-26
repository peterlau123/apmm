# UT Framework 测试

> 测试对象：**本 repo 的 UT workflow 框架代码**（`ut/workflow` 线性 + `hermes-workflow` Kanban），
> 非远程 vLLM 测试本身。目标：覆盖框架功能、度量吞吐、修复框架 bug。

---

## 状态

| Phase | 内容 | 状态 |
|-------|------|------|
| L1 单测 | 框架函数级正确性 | ✅ 148 passed / 2 skipped |
| L2 mock | 8/16/32 合成用例吞吐 | ✅ 53K–197K cases/min |
| L3 real | 真实远程端到端 | ✅ 快测 8/8；retry 暴露 4 bug |
| Phase 5 | 框架 bug 修复 | ✅ 4 bug 全修，无回归 |
| **L4 Kanban** | 3 Gateway 真机编排 | ⏳ 待用户协同 |

---

## 目录导航

```
framework_test/
├── README.md            # 本文件（总入口）
├── results/             # 结果数据
│   ├── L1_baseline.txt
│   ├── L2_results.json
│   ├── L3_fast_results.json
│   ├── L3_retry_results.json
│   └── L3_rollback.txt
└── reports/             # 分析报告
    ├── analysis_report.md       # 吞吐分析 + bug 修复
    ├── L3_execution_report.md   # L3 详细 bug 报告
    └── L4_guide.md              # 进度总结 + L4 开展指南 ★
```

---

## 关键链接

| 内容 | 文档 |
|------|------|
| 设计 spec | `tasks/ut/docs/designs/2026-06-20-ut-framework-test-and-perf-design.md` |
| 实现 plan | `tasks/ut/docs/plans/2026-06-20-ut-framework-test-and-perf-implementation.md` |
| **进度总结 + L4 指南** | [reports/L4_guide.md](reports/L4_guide.md) |
| 吞吐分析 | [reports/analysis_report.md](reports/analysis_report.md) |
| L3 bug 报告 | [reports/L3_execution_report.md](reports/L3_execution_report.md) |

---

## 运行方式（L1~L4）

| 层 | 跑什么 | 命令（详见下方分节） |
|----|--------|------|
| **L1** 单测 | 框架函数级正确性（148/2） | `python -m pytest tests/ut/unit -q` |
| **L2** mock 吞吐 | 8/16/32 合成用例（本地，无远程） | `python tests/ut/integration/run_pipeline_perf.py --n 8 --mode mock` |
| **L3** 真实远程 | 快测/重试子集端到端（需 bastion） | `python tests/ut/integration/run_pipeline_perf.py --n 8 --mode real --fixture …/l3_fast_subset.txt` |
| **L4** 真机 Kanban | 3 Gateway 编排（**需用户在场协同**） | 见下方 L4 分节 / [reports/L4_guide.md](reports/L4_guide.md) 第五节 |

### L1 — 单元测试
```powershell
python -m pytest tests/ut/unit -q                       # 期望 148 passed / 2 skipped
python -m pytest tests/ut/unit/test_kanban_board.py -q  # 跑单个文件
```

### L2 — mock 管道吞吐（本地，无远程）
```powershell
python tests/ut/integration/run_pipeline_perf.py --n 8  --mode mock
python tests/ut/integration/run_pipeline_perf.py --n 16 --mode mock
python tests/ut/integration/run_pipeline_perf.py --n 32 --mode mock
```

### L3 — 真实远程（需 bastion 在线）
```powershell
# 0) 起 bastion daemon（新窗口，手动输 OTP，保持运行）
python tools/agent.py serve t_h20
# 1) 快测吞吐子集（8 例，历史 passed 轻量用例）
python tests/ut/integration/run_pipeline_perf.py --n 8 --mode real --fixture tests/ut/integration/fixtures/l3_fast_subset.txt
# 2) 修复/重试子集（3 例，触发 failure-handler 重试闭环）
python tests/ut/integration/run_pipeline_perf.py --n 3 --mode real --fixture tests/ut/integration/fixtures/l3_retry_subset.txt
# 3) 3 例 smoke（薄封装）
python tests/ut/integration/run_linear_smoke.py
```

### L4 — 真机 Kanban（需用户在场协同）
```powershell
python tools/agent.py serve t_h20                       # 1) 新窗口，输 OTP
python tasks/ut/scripts/start_hermes_ut_runtime.py            # 2) 起 3 Gateway + Supervisor（非交互）
python tasks/ut/scripts/start_hermes_ut_runtime.py --status   # 3) 期望 Config + Overall [OK] READY
# 4) 飞书 apmm-ut 群发 “跑 ut workflow” → 回复 改参数 + 确认（见 L4_guide.md 5.6）
python tasks/ut/scripts/start_hermes_ut_runtime.py --stop     # 结束，停止全部服务
```
完整配置准备、依赖链时序验证、Kanban vs Linear 对比见 [reports/L4_guide.md](reports/L4_guide.md) 第五节。

---

## 下一步：L4

L4 需用户在场协同启动 Hermes Supervisor + 3 Gateway，验证 **executor → fixer 依赖链**。
完整开展步骤见 [reports/L4_guide.md](reports/L4_guide.md) 第五节。
