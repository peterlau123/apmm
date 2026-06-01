# APMM 文档中心

> **MiniMax-M2.7 模型验证框架文档导航**

---

## 主要入口

| 文档 | 说明 | 位置 |
|------|------|------|
| **[`../PROGRESS.md`](../PROGRESS.md)** | ← **进度追踪主文件（含工期计划）** | 根目录 |
| [`../WORKLOG.md`](../WORKLOG.md) | 每日详细工作记录 | 根目录 |

---

## 文档导览

### 操作指南 (guides/)

| 文档 | 说明 |
|------|------|
| [testing.md](guides/testing.md) | 单元测试执行指南 |
| [bastion.md](guides/bastion.md) | 堡垒机连接方案 |
| [environment.md](guides/environment.md) | 环境配置说明 |
| [troubleshooting.md](guides/troubleshooting.md) | 问题排查与修复 |

### 测试报告 (reports/)

| 文档/目录 | 说明 |
|------|------|
| [test-summary.md](reports/test-summary.md) | 测试数据汇总 |
| [error-analysis.md](reports/error-analysis.md) | 导入错误分类 |
| **[weekly/](reports/weekly/)** | 周报目录 |
| **[compatibility/](reports/compatibility/)** | 兼容性分析目录 |

#### 周报目录 (reports/weekly/)
- [`2026-05-25_05-29.md`](reports/weekly/2026-05-25_05-29.md) - 上周周报
- [`2026-05-30_06-05.md`](reports/weekly/2026-05-30_06-05.md) - **本周周报** ✅

#### 兼容性分析 (reports/compatibility/)
- [`2026-05-25_05-29.md`](reports/compatibility/2026-05-25_05-29.md) - vLLM与PyTorch兼容性问题分析

### 参考文档 (reference/)

| 文档 | 说明 |
|------|------|
| [workflow.md](reference/workflow.md) | 工作流程说明 |

---

## 单元测试最新数据

| 指标 | 数量 |
|------|------|
| ✅ 通过 | ~860 |
| ❌ 失败 | ~143 |
| 通过率 | ~85% |
| 剩余待运行 | ~8,500 (89%) |

---

## 文档结构

```
apmm/
├── WORKLOG.md           ← 每日工作日志（主入口）
├── PROGRESS.md          ← 总体进度概览
├── docs/
│   ├── README.md        ← 本文件（文档导航）
│   ├── guides/          ← 操作指南
│   ├── reports/
│   │   ├── test-summary.md    ← 测试数据汇总
│   │   ├── error-analysis.md  ← 导入错误分类
│   │   ├── weekly/            ← 周报目录
│   │   └── compatibility/     ← 兼容性分析
│   └── reference/        ← 参考文档
└── [子模块]
```

---

*更新时间: 2026-05-30*