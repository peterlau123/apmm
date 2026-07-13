# APMM 文档中心

> **MiniMax-M2.7 模型验证框架 - 项目级文档导航**
>
> ⚠️ **本目录只放跨子系统 / 项目级文档**（bastion / environment / ai-workflow / superpowers 框架自身）。
> 禁止接收仅服务单一 `tasks/<x>` 的详细文档（spec / plan / incident / report / 子系统运维 guide）。
>
> 归位规则见 [`AGENTS.md` §5](../AGENTS.md)。子系统文档入口：
> - UT：[`tasks/ut/docs/`](../tasks/ut/docs/README.md)
> - accuracy / performance / 其它：在 `tasks/<x>/docs/` 下镜像同样的目录骨架。

---

## 项目级指南 (guides/)

| 文档 | 说明 |
|------|------|
| [ai-workflow.md](guides/ai-workflow.md) | AI 辅助开发工作流 |
| [bastion.md](guides/bastion.md) | 堡垒机连接方案 |
| [environment.md](guides/environment.md) | 环境配置说明 |

---

## 项目级参考 (reference/)

| 文档 | 说明 |
|------|------|
| [daily-operations.md](reference/daily-operations.md) | 日常工作流程（daemon 启动 / UT / 精度评测 / 模型下载） |

---

## Superpowers 框架 (superpowers/)

通用 spec/plan 模板（superpowers 框架自身的设计文档）。**UT 相关的 spec/plan 已迁出**至 `tasks/ut/docs/{designs,plans}/`。

| 子目录 | 说明 |
|--------|------|
| [superpowers/specs/](superpowers/specs/) | 通用设计 spec（仅余非 UT 项：`2026-06-05-*`, `2026-06-08-agent-automation-design.md`） |
| [superpowers/specs/archive/](superpowers/specs/archive/) | 已废弃的早期 agent 架构 spec（4-Agent 模型、bastion-agent/environment-agent） |
| [superpowers/plans/](superpowers/plans/) | 通用实施 plan（UT plans 已迁出） |

---

## UT 文档入口

所有 UT-only 设计、事故、规范、报告均在 **[tasks/ut/docs/](../tasks/ut/docs/README.md)**：

| 子目录 | 说明 |
|--------|------|
| [tasks/ut/docs/guides/](../tasks/ut/docs/guides/) | UT 操作指南（testing / hermes-runner / ut-channels-overview …） |
| [tasks/ut/docs/designs/](../tasks/ut/docs/designs/) | UT 设计 spec（workflow / hermes / kanban / failure-handler / schema …） |
| [tasks/ut/docs/plans/](../tasks/ut/docs/plans/) | UT 实施 plan |
| [tasks/ut/docs/incidents/](../tasks/ut/docs/incidents/) | UT 事故复盘 |
| [tasks/ut/docs/reports/](../tasks/ut/docs/reports/) | UT 测试报告 / 周报 / 兼容性分析 |
| [tasks/ut/docs/discussions/](../tasks/ut/docs/discussions/) | UT 架构讨论 |
| [tasks/ut/docs/kanban/](../tasks/ut/docs/kanban/) | Kanban 模式配置 |
| [tasks/ut/docs/单元测试流程规范_v2.md](../tasks/ut/docs/单元测试流程规范_v2.md) | UT 流程规范 |

---

*更新时间: 2026-06-22*
