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
| 功能测试 | API兼容性、多卡并行 | ⏳ |
| 性能测试 | 吞吐量、延迟基准 | ⏳ |
| PyTorch验证 | 2.5.1/2.7.0兼容性 | 🔄 |

---

## 各模块进度概览

| 模块 | 进度入口 | 通过数 | 失败数 | 状态 |
|------|---------|:------:|:------:|:----:|
| **单元测试** | [unit_test/PROGRESS.md](unit_test/PROGRESS.md) | ~2,170 | ~160 | 🔄 |
| **精度测试** | [accuracy/PROGRESS.md](accuracy/PROGRESS.md) | - | - | ✅ |
| **功能测试** | [feature/PROGRESS.md](feature/PROGRESS.md) | - | - | ⏳ |
| **性能测试** | [performance/PROGRESS.md](performance/PROGRESS.md) | - | - | ⏳ |
| **PyTorch验证** | [pytorch/2.5.1/ut/PROGRESS.md](pytorch/2.5.1/ut/PROGRESS.md) | - | - | 🔄 |

---

## 环境架构

| 服务器 | IP | 用途 |
|--------|-----|------|
| t_h20 | 10.10.154.13 | 测试运行 (H20-3e×8) |
| t_ascend | 10.250.121.21 | 下载资源 (联网) |
| 堡垒机 | 10.10.192.55:22 | SSH网关 |

---

## 项目文档导航

详见 **[docs/README.md](docs/README.md)** - 项目文档中心

---

*更新时间: 2026-06-01*