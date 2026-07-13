# APMM — vLLM 验证框架 (M2.7_verify)

> 验证 **MiniMax-M2.7** 模型在 **vLLM v0.13.0** + **NVIDIA H20-3e** 环境下的功能、性能和精度。

---

## 目录结构

```
apmm/
├── .agents/          # Agent 运行状态（workflow 配置、批次数据、日志）
├── skills/           # Agent 技能定义（ut/ 下 9 个 Skill）
├── tasks/            # 任务工作区
│   ├── ut/           #   单元测试 ← 当前活跃
│   ├── compile/      #   编译测试
│   ├── accuracy/     #   精度测试
│   ├── feature/      #   功能测试
│   └── performance/  #   性能测试
├── tools/            # 工具脚本（SSH 代理、飞书通知）
├── docs/             # 项目文档（指南、参考、归档）
│
├── README.md         # 本文件 — 项目总入口
├── AGENTS.md         # Agent 工作指南
├── PROGRESS.md       # 总体进度
```

---

## 任务模块

| 模块 | 入口 | 说明 |
|------|------|------|
| **单元测试** | [tasks/ut/README.md](tasks/ut/README.md) | UT Workflow 总入口，含完整目录树、架构图、数据流 |
| 编译测试 | [tasks/compile/README.md](tasks/compile/README.md) | vLLM 离线编译验证 |
| 精度测试 | tasks/accuracy/ | 精度评测（evalscope） |
| 功能测试 | tasks/feature/ | API 兼容性、多卡并行 |
| 性能测试 | tasks/performance/ | 吞吐量、延迟基准 |

---

## 文档导航

| 文档 | 说明 |
|------|------|
| **[PROGRESS.md](PROGRESS.md)** | 项目总进度（各模块状态汇总） |
| **[AGENTS.md](AGENTS.md)** | Agent 工作指南（环境、Workflow、规范） |
| **[docs/](docs/)** | 操作指南、参考文档、归档 |

---

## 快速开始

1. 了解环境 → [AGENTS.md § 远程环境](AGENTS.md#远程环境)
2. 执行单元测试 → [tasks/ut/README.md](tasks/ut/README.md)
3. 查看进度 → [PROGRESS.md](PROGRESS.md)

---

*更新时间: 2026-06-12*
