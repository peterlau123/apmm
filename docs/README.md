# APMM 文档中心

> **MiniMax-M2.7 模型验证框架 - 项目级文档导航**

---

## 主要入口

| 文档 | 说明 |
|------|------|
| **[PROGRESS.md](../PROGRESS.md)** | 项目总进度概览（各模块汇总） |

---

## 各模块文档入口

| 模块 | 文档入口 | 说明 |
|------|---------|------|
| **单元测试** | [unit_test/docs/](../unit_test/docs/) | UT目标、进度、报告、指南 |
| **精度测试** | [accuracy/](../accuracy/) | GPQA-Diamond, Multi-SWE-bench |
| **功能测试** | [feature/](../feature/) | API兼容性、多卡并行 |
| **性能测试** | [performance/](../performance/) | 吞吐量、延迟基准 |
| **PyTorch验证** | [pytorch/](../pytorch/) | PyTorch兼容性验证 |

---

## 项目级指南 (guides/)

| 文档 | 说明 |
|------|------|
| [bastion.md](guides/bastion.md) | 堡垒机连接方案 |
| [environment.md](guides/environment.md) | 环境配置说明 |
| [troubleshooting.md](guides/troubleshooting.md) | 问题排查与修复 |

---

## 项目级参考文档 (reference/)

| 文档 | 说明 |
|------|------|
| [workflow.md](reference/workflow.md) | 工作流程说明 |

---

## 文档结构

```
apmm/
├── PROGRESS.md          # 项目总进度（各模块汇总）
├── README.md            # 项目说明
│
├── docs/                # 【项目级文档】
│   ├── README.md        # 本文件
│   ├── guides/          # 环境配置、堡垒机、问题排查
│   └── reference/       # 工作流程、架构说明
│
├── unit_test/           # 【单元测试模块】
│   ├── PROGRESS.md      # UT详细进度
│   ├── GOAL.md          # UT目标
│   ├── WORKLOG.md       # UT工作日志
│   └── docs/            # UT专用文档
│       ├── guides/      # 测试执行指南
│       ├── reports/     # 测试报告、周报、兼容性分析
│       └── reference/   # UT参考文档
│
├── accuracy/            # 【精度测试模块】
├── feature/             # 【功能测试模块】
├── performance/         # 【性能测试模块】
└── pytorch/             # 【PyTorch验证模块】
```

---

*更新时间: 2026-06-01*