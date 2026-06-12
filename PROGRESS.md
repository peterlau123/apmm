# APMM 项目进度追踪

> **MiniMax-M2.7 模型验证框架** - vLLM v0.13.0 + PyTorch 2.5.1
> **各验证模块进度汇总**

---

## 项目总目标

完成 MiniMax-M2.7 模型在 NVIDIA H20-3e GPU 环境下的全面验证：

| 模块 | 目标 | 状态 |
|------|------|:----:|
| 单元测试 | vLLM pytest 全通过 | 🔄 |
| 精度测试 | GPQA-Diamond, Multi-SWE-bench | ✅ |
| 功能测试 | API 兼容性、多卡并行 | ⏳ |
| 性能测试 | 吞吐量、延迟基准 | ⏳ |
| PyTorch 验证 | 2.5.1/2.7.0 兼容性 | 🔄 |

---

## 各模块进度

| 模块 | 进度入口 | 通过数 | 失败数 | 状态 |
|------|---------|:------:|:------:|:----:|
| **单元测试** | [tasks/ut/PROGRESS.md](tasks/ut/PROGRESS.md) | 10,805 | 9,273 | 🔄 |
| **编译测试** | [tasks/compile/PROGRESS.md](tasks/compile/PROGRESS.md) | - | - | ✅ |
| **精度测试** | [tasks/accuracy/PROGRESS.md](tasks/accuracy/PROGRESS.md) | - | - | ✅ |
| **功能测试** | [tasks/feature/](tasks/feature/) | - | - | ⏳ |
| **性能测试** | [tasks/performance/](tasks/performance/) | - | - | ⏳ |

---

## 环境架构

| 服务器 | IP | 用途 |
|--------|-----|------|
| t_h20 | 10.10.154.13 | 测试运行 (H20-3e×8) |
| t_ascend | 10.250.121.21 | 下载资源 (联网) |
| 堡垒机 | 10.10.192.55:22 | SSH 网关 |

详见 [docs/guides/environment.md](docs/guides/environment.md)

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 项目说明、快速开始 |
| [AGENTS.md](AGENTS.md) | Agent 工作指南 |
| [docs/README.md](docs/README.md) | 文档中心索引 |

---

*更新时间: 2026-06-12*
