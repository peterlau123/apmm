# UT 文档中心

> **vLLM pytest 单元测试套件 — 所有 UT 专属文档**
>
> ⚠️ **本目录是 UT 文档唯一收纳处**。项目级 `docs/` 禁止接收 UT-only 文档；归位规则见 [`AGENTS.md` §5](../../../AGENTS.md)。
>
> 主入口在父目录的 [`tasks/ut/README.md`](../README.md)。本文件是 UT **文档**（设计 / 指南 / 报告 / 事故）的导航。

---

## 主要入口

| 文档 | 说明 |
|------|------|
| **[../README.md](../README.md)** | UT Workflow 总入口 |
| **[../GOAL.md](../GOAL.md)** | 测试目标与完成标准 |
| **[../PROGRESS.md](../PROGRESS.md)** | 实时进度（数字唯一来源） |
| **[../WORKLOG.md](../WORKLOG.md)** | 每日工作日志索引 |
| **[../todo.md](../todo.md)** | 待办事项 & 设计决策 |
| **[单元测试流程规范_v2.md](单元测试流程规范_v2.md)** | UT 完整流程规范 |

---

## 操作指南 (guides/)

| 文档 | 说明 |
|------|------|
| [ut-channels-overview.md](guides/ut-channels-overview.md) | **两个通道总览**（ut/workflow + hermes-workflow，含 mermaid 图） |
| [testing.md](guides/testing.md) | 测试执行指南（环境 / 命令 / 过滤） |
| [troubleshooting.md](guides/troubleshooting.md) | vLLM 修复操作指南（2.5.1_ut_verify 分支） |
| [hermes-supervisor-service.md](guides/hermes-supervisor-service.md) | ut-supervisor Hermes Agent systemd 部署 |
| [hermes-gateway-service.md](guides/hermes-gateway-service.md) | hermes-gateway@ 3 实例 systemd 部署 |
| [hermes-windows-service.md](guides/hermes-windows-service.md) | **Windows NSSM 部署**（含 macOS launchd 简表） |
| [hermes-runner.md](guides/hermes-runner.md) | Hermes Runner 操作指南 |
| [manual_operations.md](guides/manual_operations.md) | 手动处理收集错误 |
| [error-stats-guide.md](guides/error-stats-guide.md) | 错误统计 & 分类指南 |
| [resume-tools-guide.md](guides/resume-tools-guide.md) | **Resume工具集使用指南**（workflow_state_manager + resume.py + loop_executor.py） |

---

## 设计 (designs/)

UT 相关 spec 文档（从 `docs/superpowers/specs/` 迁入）：

| 文档 | 说明 |
|------|------|
| [2026-07-03-resume-mechanism-design.md](designs/2026-07-03-resume-mechanism-design.md) | **Resume机制改进设计**（三重保障：强制更新+强制输出+硬性约束） |
| [2026-06-11-ut-workflow-design.md](designs/2026-06-11-ut-workflow-design.md) | UT Workflow 原始设计 |
| [2026-06-12-ut-workflow-kanban-integration-design.md](designs/2026-06-12-ut-workflow-kanban-integration-design.md) | Kanban 集成 |
| [2026-06-14-ut-workflow-fixes-design.md](designs/2026-06-14-ut-workflow-fixes-design.md) | Workflow 修复设计 |
| [2026-06-15-ut-workflow-improvements-design.md](designs/2026-06-15-ut-workflow-improvements-design.md) | Workflow 改进 |
| [2026-06-18-hermes-workflow-dual-channel-design.md](designs/2026-06-18-hermes-workflow-dual-channel-design.md) | **Hermes 双通道架构（v5 当前版本）** |
| [2026-06-22-ut-tier-fixtures-and-agent-intent-design.md](designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md) | **L1–L4 测试梯度 fixture + Agent 意图识别（Draft）** |
| [2026-06-20-ut-framework-test-and-perf-design.md](designs/2026-06-20-ut-framework-test-and-perf-design.md) | Framework test & perf 设计 |
| [2026-06-10-ut-schema-unification-design.md](designs/2026-06-10-ut-schema-unification-design.md) | Manifest schema 统一 |
| [2026-06-11-ut-filter-rules-consolidation-design.md](designs/2026-06-11-ut-filter-rules-consolidation-design.md) | 过滤规则合并 |
| [2026-06-11-log-parse-and-transfer-design.md](designs/2026-06-11-log-parse-and-transfer-design.md) | 日志解析与传输 |
| [2026-06-12-failure-handler-review-design.md](designs/2026-06-12-failure-handler-review-design.md) | failure-handler 重构设计 |
| [2026-06-12-failure-handler-review-analysis.md](designs/2026-06-12-failure-handler-review-analysis.md) | failure-handler 10 项决策分析 |
| [failure-handler-progress-state.md](designs/failure-handler-progress-state.md) | failure-handler 进度状态 |
| [hermes-kanban-v1-spec.pdf](designs/hermes-kanban-v1-spec.pdf) | Hermes Kanban v1 spec |
| [agents/](designs/agents/) | Agent 子系统详细设计（supervisor-agent / unit-test-executor-agent） |

---

## 实施 plan (plans/)

UT 相关实施计划（从 `docs/superpowers/plans/` 迁入）：

| 文档 | 说明 |
|------|------|
| [2026-06-19-hermes-workflow-foundation.md](plans/2026-06-19-hermes-workflow-foundation.md) | **Hermes Workflow 基础** |
| [2026-06-20-hermes-workflow-deployment.md](plans/2026-06-20-hermes-workflow-deployment.md) | Hermes Workflow 部署 |
| [2026-06-20-ut-framework-test-and-perf-implementation.md](plans/2026-06-20-ut-framework-test-and-perf-implementation.md) | Framework test & perf 实施 |
| [2026-06-15-ut-workflow-improvements.md](plans/2026-06-15-ut-workflow-improvements.md) | Workflow 改进实施 |
| [2026-06-14-ut-workflow-fixes.md](plans/2026-06-14-ut-workflow-fixes.md) | Workflow 修复实施 |
| [2026-06-12-ut-workflow-kanban-integration.md](plans/2026-06-12-ut-workflow-kanban-integration.md) | Kanban 集成实施 |
| [2026-06-11-ut-workflow-optimization.md](plans/2026-06-11-ut-workflow-optimization.md) | Workflow 优化实施 |

---

## 事故复盘 (incidents/)

从 `docs/incidents/` 迁入（UT 是 incidents 的唯一来源，故归属 UT）：

| 文档 | 说明 |
|------|------|
| **[incidents/README.md](incidents/README.md)** | 事故索引（按时间倒序） |
| [2026-06-22-l4-fabrication.md](incidents/2026-06-22-l4-fabrication.md) | L4 Stage-3 Fabrication 事故（run `ut-20260621-234651`） |

---

## 测试报告 (reports/)

| 子目录 / 文档 | 说明 |
|--------------|------|
| [test-summary.md](reports/test-summary.md) | 测试结果汇总 |
| [reports/weekly/](reports/weekly/) | UT 周报 |
| [reports/compatibility/](reports/compatibility/) | 兼容性分析（vLLM × PyTorch） |

---

## 架构讨论 (discussions/)

| 文档 | 说明 |
|------|------|
| [2026-06-09-about_agents_architecture_and_workflow_design.md](discussions/2026-06-09-about_agents_architecture_and_workflow_design.md) | Agent 架构 & Workflow 设计讨论 |
| [2026-06-18-hermes-runner-bastion-otp-design.md](discussions/2026-06-18-hermes-runner-bastion-otp-design.md) | Hermes Runner Bastion OTP 设计讨论 |

---

## Kanban 模式 (kanban/)

| 文档 | 说明 |
|------|------|
| [kanban/README.md](kanban/README.md) | Kanban 模式完整配置 |

---

*更新时间: 2026-06-22*
