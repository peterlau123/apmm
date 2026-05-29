# APMM - Assisted Proof of Model Minimax-M2.7

> **MiniMax-M2.7 模型验证框架 | vLLM 推理引擎适配测试**

---

## 项目简介

**APMM** = Assisted Proof of Model Minimax-M2.7

验证 **vLLM v0.13.0** 在 NVIDIA H20-3e GPU 环境下的运行情况，为 MiniMax-M2.7 模型生产部署做准备。

| 模块 | 内容 | 状态 |
|------|------|:----:|
| 单元测试 | vLLM pytest 测试套件 | 🔄 |
| 功能测试 | API兼容性、多卡并行 | ⏳ |
| 性能测试 | 吞吐量、延迟基准 | ⏳ |
| 精度测试 | GPQA-Diamond, Multi-SWE-bench | ✅ |
| PyTorch验证 | 2.5.1/2.7.0兼容性 | 🔄 |

---

## 快速开始

### 1. 检查连接

```powershell
python agent.py profiles
python agent.py -p t_h20 ping
```

### 2. 运行测试

```powershell
python agent.py -p t_h20 shell
# 进入容器执行
sudo docker exec -it v0.13.0_torch2.5.1_compile bash
pytest tests/test_xxx.py -vv
```

---

## 文档导航

详见 **[docs/README.md](docs/README.md)** - 文档中心索引

| 文档类别 | 路径 | 说明 |
|----------|------|------|
| 操作指南 | [docs/guides/](docs/guides/) | 测试执行、环境配置 |
| 测试报告 | [docs/reports/](docs/reports/) | 测试结果汇总 |
| 参考文档 | [docs/reference/](docs/reference/) | 工作流程、架构 |

---

## 目录结构

```
apmm/
├── README.md          # 本文件
├── PROGRESS.md        # 实时进度
├── docs/              # 文档中心
├── scripts/           # 修复脚本
├── patches/           # 代码补丁
├── accuracy/          # 精度测试
├── feature/           # 功能测试
├── performance/       # 性能测试
├── unit_test/         # 单元测试
└── pytorch/           # PyTorch验证
```

---

## 进度追踪

**总体进度**: [PROGRESS.md](PROGRESS.md)

当前单元测试通过率 ~75% (800+ passed)

---

## 环境架构

| 服务器 | IP | 用途 |
|--------|-----|------|
| t_h20 | 10.10.154.13 | 测试运行 (H20-3e×8) |
| t_ascend | 10.250.121.21 | 下载资源 (联网) |
| 堡垒机 | 10.10.192.55:22 | SSH网关 |

---

*详细文档见 [docs/README.md](docs/README.md)*