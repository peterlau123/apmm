# vLLM 验证框架 (M2.7_verify)

MiniMax-M2.7 模型和 vLLM 推理引擎的验证框架。

---

## 项目简介

本框架用于验证 **vLLM v0.13.0** 在 NVIDIA H20-3e GPU (8卡, 143GB显存) 环境下的运行情况，为 MiniMax-M2.7 模型部署做准备。

### 验证范围

| 模块 | 内容 | 状态 |
|------|------|------|
| **单元测试** | vLLM pytest 测试套件 (856个测试文件) | 进行中 |
| **功能测试** | vLLM 各版本功能验证 | 待开始 |
| **性能测试** | 吞吐量、延迟基准测试 | 待开始 |
| **精度测试** | GPQA-D, Multi-SWE-bench 评测 | 已完成部分 |

---

## 快速开始

### 1. 检查远程连接

```powershell
python agent.py profiles          # 查看可用服务器
python agent.py -p t_h20 ping     # 检查 daemon 状态
```

### 2. 查看远程环境

```powershell
python agent.py -p t_h20 run "ls /gpfs/gcsp/M2.7_verify/"
python agent.py -p t_h20 run "sudo docker ps -a"
```

### 3. 运行测试

进入容器：

```powershell
python agent.py -p t_h20 shell
# 然后在远程执行：
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
cd /gpfs/gcsp/M2.7_verify/vllm
pytest -vv tests/test_config.py
```

或远程执行：

```powershell
python agent.py -p t_h20 run --timeout 300 "sudo docker exec v0.13.0_torch2.5.1_ut pytest -vv /gpfs/gcsp/M2.7_verify/vllm/tests/test_config.py"
```

---

## 目录结构

```
apmm/
├── accuracy/           # 精度测试
│   ├── GPQA-D/         # GPQA-Diamond 评测
│   └── Multi-SWE/      # Multi-SWE-bench 评测
├── feature/            # 功能测试
├── performance/        # 性能测试
├── unit_test/          # 单元测试
├── pytorch/            # PyTorch 验证
├── scripts/            # 通用脚本
├── utilities/          # 工具脚本
├── docs/               # 项目文档
├── agent.py            # SSH 代理脚本
├── CLAUDE.md           # AI Agent 行为准则
├── AGENTS.md           # AI Agent 项目指南
└── README.md           # 本文件
```

---

## 测试环境

### 硬件配置

| 服务器 | IP | 配置 |
|--------|-----|------|
| t_ascend | 10.250.121.21 | 联网机器 (下载依赖) |
| t_h20 | 10.10.154.13 | NVIDIA H20-3e × 8, /gpfs 共享存储 |

### Docker 容器

| 容器名 | 用途 |
|--------|------|
| `v0.13.0_torch2.5.1_ut` | 单元测试 |
| `v0.13.0_torch2.5.1_compile` | 编译测试 |
| `m2.7_v0.13.0_evalscope` | 精度评测 |
| `m2.7_v0.13.0_port7777` | vLLM 服务 |

---

## 进度跟踪

详见 [PROGRESS.md](./PROGRESS.md) 和各模块的 PROGRESS.md 文件。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [AGENTS.md](./AGENTS.md) | AI Agent 项目工作指南 |
| [CLAUDE.md](./CLAUDE.md) | AI Agent 行为准则 |
| [docs/bastion.md](./docs/bastion.md) | 堡垒机连接方案 |
| [docs/README.md](./docs/README.md) | 单元测试执行指南 |
| [docs/environment.md](./docs/environment.md) | 环境配置说明 |
| [docs/workflow.md](./docs/workflow.md) | 工作流程说明 |
| [pytorch/README.md](./pytorch/README.md) | PyTorch 验证说明 |