# 🚀 APMM - AI Performance Model Management

> **MiniMax-M2.7 模型 & vLLM 推理引擎验证框架**

---

## 📖 项目名称由来

**APMM** = **A**I **P**erformance **M**odel **M**anagement

| 字母 | 含义 | 说明 |
|:---:|------|------|
| **A** | AI / Accuracy | 人工智能 & 模型精度验证 |
| **P** | Performance | 推理性能基准测试 |
| **M** | Model | 大语言模型适配验证 |
| **M** | Management | 测试流程管理与追踪 |

APMM 是一个综合性验证框架，旨在为大语言模型部署提供**精度 ✅**、**性能 ⚡**、**功能 🔧** 的全方位验证能力。

---

## 🎯 项目简介

本框架用于验证 **vLLM v0.13.0** 在 NVIDIA H20-3e GPU 环境下的运行情况，为 MiniMax-M2.7 模型生产部署做准备。

### 验证范围

| 模块 | 内容 | 状态 |
|------|------|:----:|
| 🧪 **单元测试** | vLLM pytest 测试套件 (856个文件) | 🔄 |
| 🔧 **功能测试** | API兼容性、多卡并行、量化支持 | ⏳ |
| ⚡ **性能测试** | 吞吐量、延迟、显存基准测试 | ⏳ |
| 🎯 **精度测试** | GPQA-Diamond, Multi-SWE-bench | ✅ |
| 🐍 **PyTorch验证** | 多版本兼容性 (2.5.1/2.7.0) | 🔄 |

---

## 🏗️ 测试环境架构

```
┌─────────────────────────────────────────────────────────────┐
│                    本地开发机 (Windows)                       │
│                         agent.py                             │
│                    SSH over Bastion 🔐                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               堡垒机 (10.10.192.55:22)                        │
│                 齐治 Shterm v3.3.13                          │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
┌─────────────────────┐               ┌─────────────────────┐
│   📥 t_ascend       │               │   🖥️ t_h20          │
│   10.250.121.21     │               │   10.10.154.13      │
│   ───────────────── │               │   ───────────────── │
│   • 联网机器        │               │   • NVIDIA H20-3e×8 │
│   • 下载依赖/模型   │               │   • 143GB显存/卡    │
│   • 无/gpfs挂载     │               │   • Docker容器      │
└─────────────────────┘               │   • /gpfs 1.9PB     │
                                      └─────────────────────┘
```

### 🖥️ 硬件配置

| 服务器 | GPU | 存储 | 用途 |
|--------|-----|------|------|
| t_h20 | NVIDIA H20-3e × 8 | /gpfs 1.9PB | 运行测试 |
| t_ascend | 无 | 本地NVMe | 下载资源 |

---

## 🚀 快速开始

### 1️⃣ 检查连接状态

```powershell
# 查看 profile 配置
python agent.py profiles

# 检查 daemon 状态
python agent.py -p t_h20 ping
python agent.py -p t_ascend ping
```

### 2️⃣ 查看远程环境

```powershell
# 查看 M2.7_verify 目录
python agent.py -p t_h20 run "ls /gpfs/gcsp/M2.7_verify/"

# 查看 Docker 容器
python agent.py -p t_h20 run "sudo docker ps -a"

# 查看 GPU 状态
python agent.py -p t_h20 run "nvidia-smi"
```

### 3️⃣ 运行测试

**方式一：交互式 Shell**

```powershell
python agent.py -p t_h20 shell
# 远程执行：
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
cd /gpfs/gcsp/M2.7_verify/vllm
pytest -vv tests/test_seed_behavior.py
```

**方式二：远程命令**

```powershell
python agent.py -p t_h20 run --timeout 300 `
  "sudo docker exec v0.13.0_torch2.5.1_ut pytest -vv /gpfs/gcsp/M2.7_verify/vllm/tests/test_config.py"
```

---

## 📁 目录结构

```
apmm/
├── 🎯 accuracy/          # 精度测试模块
│   ├── GPQA-D/          # GPQA-Diamond 科学问答
│   └── Multi-SWE/       # 多语言代码修复
├── 🔧 feature/           # 功能测试模块
│   ├── v0.11.1/         # vLLM v0.11.1
│   ├── v0.13.0/         # vLLM v0.13.0 (主验证版本)
│   ├── v0.17.0/         # vLLM v0.17.0
│   └── vllm_test/       # 通用功能测试
├── ⚡ performance/       # 性能测试模块
│   ├── v0.13.0/         # 性能基准
│   └── monitor.py       # GPU监控脚本
├── 🧪 unit_test/         # 单元测试模块
├── 🐍 pytorch/           # PyTorch 验证
│   └── 2.5.1/           # PyTorch 2.5.1
│       ├── compile/     # 编译测试
│       ├── ut/          # 单元测试
│       └── patches/     # 兼容性补丁
├── 📜 scripts/           # 通用脚本
├── 🔨 utilities/         # 工具脚本
├── 📚 docs/              # 项目文档
│   ├── bastion.md       # 堡垒机方案
│   ├── environment.md   # 环境配置
│   ├── workflow.md      # 工作流程
│   └── README.md        # 单元测试指南
├── 🔐 agent.py           # SSH 堡垒机代理
├── 📖 AGENTS.md          # AI Agent 项目指南
├── 📝 CLAUDE.md          # AI Agent 行为准则
├── 📊 PROGRESS.md        # 进度总览
└── 📄 README.md          # 本文件
```

---

## 🐳 Docker 容器

| 容器名 | 镜像 | 用途 | 状态 |
|--------|------|------|:----:|
| `v0.13.0_torch2.5.1_ut` | vllm/vllm-openai:v0.13.0 | 单元测试 | ✅ Running |
| `v0.13.0_torch2.5.1_compile` | vllm/vllm-openai:v0.13.0 | 编译测试 | ✅ Running |
| `m2.7_v0.13.0_evalscope` | evalscope_tools:0312 | 精度评测 | ✅ Running |
| `m2.7_v0.13.0_port7777` | vllm/vllm-openai:v0.13.0 | vLLM服务 | ✅ Running |

---

## 📈 进度跟踪

| 模块 | 进度 | 详情 |
|------|:----:|------|
| 单元测试 | 🔄 6/48 | [unit_test/PROGRESS.md](./unit_test/PROGRESS.md) |
| 功能测试 | ⏳ 0% | [feature/PROGRESS.md](./feature/PROGRESS.md) |
| 性能测试 | ⏳ 0% | [performance/PROGRESS.md](./performance/PROGRESS.md) |
| 精度测试 | ✅ 部分 | [accuracy/PROGRESS.md](./accuracy/PROGRESS.md) |
| PyTorch | 🔄 部分 | [pytorch/2.5.1/PROGRESS.md](./pytorch/2.5.1/PROGRESS.md) |

总体进度详见 [PROGRESS.md](./PROGRESS.md)。

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [AGENTS.md](./AGENTS.md) | 🤖 AI Agent 项目工作指南 |
| [CLAUDE.md](./CLAUDE.md) | 📝 AI Agent 行为准则 |
| [PROGRESS.md](./PROGRESS.md) | 📊 项目进度总览 |
| [docs/bastion.md](./docs/bastion.md) | 🔐 堡垒机连接方案 |
| [docs/environment.md](./docs/environment.md) | ⚙️ 环境配置说明 |
| [docs/workflow.md](./docs/workflow.md) | 🔁 工作流程说明 |
| [docs/README.md](./docs/README.md) | 🧪 单元测试执行指南 |

---

## 🔗 远程路径映射

| 本地目录 | 远程目录 | 远程路径 |
|:--------:|:--------:|----------|
| `accuracy/` | `accuracy_test/` | `/gpfs/gcsp/M2.7_verify/accuracy_test/` |
| `feature/` | `feature_test/` | `/gpfs/gcsp/M2.7_verify/feature_test/` |
| `performance/` | `performance_test/` | `/gpfs/gcsp/M2.7_verify/performance_test/` |
| `pytorch/` | `pytorch_verify/` | `/gpfs/gcsp/M2.7_verify/pytorch_verify/` |
| `vllm源码` | `vllm/` | `/gpfs/gcsp/M2.7_verify/vllm/` |

---

## 🛠️ 测试过滤规则

运行 pytest 时排除不支持的平台：

```bash
pytest tests/ \
    --ignore-glob="tests/**/rocm*" \     # AMD GPU
    --ignore-glob="tests/**/tpu*" \      # TPU
    --ignore-glob="tests/**/multimodal*" \  # 多模态
    --ignore-glob="tests/**/*image*.py" \
    --ignore-glob="tests/**/*video*.py" \
    -vv -s
```

---

## 📋 已知问题

| 问题 ⚠️ | 原因 | 解决方案 |
|---------|------|----------|
| LoRA 导入错误 | PyTorch 类型签名不兼容 | 检查版本 |
| Triton 导入失败 | Triton 版本兼容性 | 更新 Triton |
| HF 模型无法访问 | 未联网机器 | 预下载到 /gpfs |

---

## 📜 更新日志

### 2026-05-25
- ✅ 创建完整项目文档体系
- ✅ 建立 Git 文件追踪
- ✅ 完善 README.md

### 2026-05-22
- ✅ 创建单元测试进度跟踪
- ✅ 完成 GPQA-Diamond 初次评测

---

*Made with ❤️ for MiniMax-M2.7 verification*