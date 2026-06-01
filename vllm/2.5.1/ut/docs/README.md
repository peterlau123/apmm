# 单元测试文档中心

> **vLLM pytest 测试套件文档导航**

---

## 主要入口

| 文档 | 说明 |
|------|------|
| **[../PROGRESS.md](../PROGRESS.md)** | UT详细进度（主入口） |
| **[../GOAL.md](../GOAL.md)** | 单元测试目标 |
| **[../WORKLOG.md](../WORKLOG.md)** | 每日工作日志 |

---

## 测试指南 (guides/)

| 文档 | 说明 |
|------|------|
| [testing.md](guides/testing.md) | 测试执行指南（环境、命令、过滤规则） |

---

## 测试报告 (reports/)

| 文档/目录 | 说明 |
|------|------|
| [test-summary.md](reports/test-summary.md) | 测试结果汇总 |
| [error-analysis.md](reports/error-analysis.md) | 导入错误分类详情 |
| **[weekly/](reports/weekly/)** | 周报目录 |
| **[compatibility/](reports/compatibility/)** | 兼容性分析目录 |

### 周报目录 (reports/weekly/)
- [`2026-05-25_05-29.md`](reports/weekly/2026-05-25_05-29.md) - 上周周报
- [`2026-05-30_06-05.md`](reports/weekly/2026-05-30_06-05.md) - 本周周报 ✅
- [`单元测试验证周报5.11-5.15.pdf`](reports/weekly/单元测试验证周报5.11-5.15.pdf) - 历史周报

### 兼容性分析 (reports/compatibility/)
- [`2026-05-25_05-29.md`](reports/compatibility/2026-05-25_05-29.md) - vLLM与PyTorch兼容性问题分析

---

## 文档结构

```
unit_test/
├── PROGRESS.md          # UT详细进度（主入口）
├── GOAL.md              # UT目标
├── WORKLOG.md           # UT工作日志
├── README.md            # UT说明
│
└── docs/                # UT专用文档
    ├── README.md        # 本文件（文档导航）
    ├── guides/          # 测试执行指南
    │   └── testing.md
    ├── reports/         # 测试报告
    │   ├── test-summary.md
    │   ├── error-analysis.md
    │   ├── compatibility/
    │   └ weekly/
    └── reference/       # UT参考文档
```

---

## 当前测试数据

| 指标 | 数量 |
|------|:----:|
| ✅ 累计通过 | ~2,170 |
| ❌ 累计失败 | ~160 |
| 通过率 | ~99% |
| 覆盖率 | ~22.9% |

---

*更新时间: 2026-06-01*