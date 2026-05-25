# AGENTS.md

AI Agent 工作指南 - 本项目为 **vLLM 验证框架** (M2.7_verify)

---

## 项目概述

这是一个验证框架，用于验证 **MiniMax-M2.7** 模型和 **vLLM** (v0.13.0) 推理引擎在 NVIDIA H20-3e GPU 环境下的功能、性能和精度。

| 组件 | 版本 | 说明 |
|------|------|------|
| vLLM | v0.13.0 | 高性能 LLM 推理引擎 |
| MiniMax-M2.7 | - | 待验证的大语言模型 |
| PyTorch | 2.5.1 / 2.7.0 | 深度学习框架 |
| CUDA | 12.4 / 12.8 | NVIDIA CUDA |
| GPU | NVIDIA H20-3e | 8卡, 143GB显存/卡 |

---

## 目录结构

```
apmm/
├── accuracy/           # 精度测试模块
│   ├── GPQA-D/         # GPQA-Diamond 评测
│   └── Multi-SWE/      # Multi-SWE-bench 评测
├── feature/            # 功能测试模块
│   ├── v0.11.1/        # vLLM v0.11.1 功能验证
│   ├── v0.13.0/        # vLLM v0.13.0 功能验证
│   ├── v0.17.0/        # vLLM v0.17.0 功能验证
│   ├── latest/         # 最新版本功能验证
│   └── vllm_test/      # vLLM 通用功能测试
├── performance/        # 性能测试模块
│   ├── v0.13.0/        # vLLM v0.13.0 性能验证
│   ├── latest/         # 最新版本性能验证
│   └── monitor.py      # 性能监控脚本
├── unit_test/          # 单元测试模块
├── pytorch/            # PyTorch 验证模块
│   └── 2.5.1/          # PyTorch 2.5.1 验证
│       ├── compile/    # 编译测试
│       ├── ut/         # 单元测试
│       └── patches/    # 兼容性补丁
├── scripts/            # 通用脚本
├── utilities/          # 工具脚本
├── docs/               # 项目文档
├── agent.py            # SSH 堡垒机代理
├── CLAUDE.md           # AI Agent 行为准则
├── AGENTS.md           # 本文件
├── README.md           # 项目总览
└── PROGRESS.md         # 总体进度跟踪
```

---

## 远程环境路径映射

本地目录名与远程服务器目录名对照：

| 本地目录 | 远程目录 | 远程路径 |
|---------|---------|---------|
| `accuracy/` | `accuracy_test/` | `/gpfs/gcsp/M2.7_verify/accuracy_test/` |
| `feature/` | `feature_test/` | `/gpfs/gcsp/M2.7_verify/feature_test/` |
| `performance/` | `performance_test/` | `/gpfs/gcsp/M2.7_verify/performance_test/` |
| `pytorch/` | `pytorch_verify/` | `/gpfs/gcsp/M2.7_verify/pytorch_verify/` |
| `unit_test/` | `unit_test/` | `/gpfs/gcsp/M2.7_verify/unit_test/` |
| `vllm源码` | `vllm/` | `/gpfs/gcsp/M2.7_verify/vllm/` |

---

## 测试环境架构

```
本机 (Windows + VPN)
    │
    │  agent.py (SSH over Bastion)
    ▼
堡垒机 10.10.192.55:22 (齐治 Shterm)
    │
    ├──────────────────────────────────────┐
    │                                      │
    ▼                                      ▼
t_ascend (10.250.121.21)              t_h20 (10.10.154.13)
- 联网机器                             - 未联网机器
- 下载依赖/模型                         - NVIDIA H20-3e × 8
- 无/gpfs挂载                           - Docker容器运行测试
                                       - /gpfs 共享存储 (1.9PB)
```

---

## Agent 工作命令

### 连接远程服务器

```powershell
# 检查 daemon 状态
python agent.py -p t_ascend ping
python agent.py -p t_h20 ping

# 执行远程命令
python agent.py -p t_h20 run "ls /gpfs/gcsp/M2.7_verify/"

# 进入交互式 shell
python agent.py -p t_h20 shell
```

### 运行测试

```bash
# 在 t_h20 容器内执行 pytest
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
cd /gpfs/gcsp/M2.7_verify/vllm
pytest -vv tests/test_xxx.py 2>&1 | tee ut_logs/xxx_ut.log
```

或通过 agent.py 远程执行：

```powershell
python agent.py -p t_h20 run --timeout 300 "sudo docker exec v0.13.0_torch2.5.1_ut bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv tests/test_seed_behavior.py'"
```

---

## 测试过滤规则

运行 pytest 时需排除不支持的平台：

```bash
pytest tests/ \
    --ignore-glob="tests/**/rocm*" \
    --ignore-glob="tests/**/tpu*" \
    --ignore-glob="tests/**/multimodal*" \
    --ignore-glob="tests/**/nixl*" \
    --ignore-glob="tests/**/ec_connector*" \
    --ignore-glob="tests/**/*image*.py" \
    --ignore-glob="tests/**/*video*.py" \
    --ignore-glob="tests/**/*audio*" \
    --ignore-glob="tests/**/encoder*" \
    --ignore-glob="tests/**/prithvi*" \
    -vv -s
```

---

## 评测工具

| 工具 | 用途 | 数据集 |
|------|------|--------|
| evalscope | 精度评测 | GPQA-Diamond, GSM8K, MATH-500, MMLU-Pro |
| Multi-SWE-bench | 代码修复评测 | 7种语言, 1632个实例 |

---

## 文件追踪策略

本项目使用本地 Git 仓库追踪关键脚本和文档，不追踪：

- 模型文件 (`*.safetensors`, `*.bin`)
- 压缩包 (`*.tar`, `*.tar.gz`, `*.zip`)
- 数据集缓存 (`datasets/`, `hf_hub/`, `modelscope/`)
- 日志输出 (`*.log`, `outputs/`, `logs/`)
- Python缓存 (`__pycache__/`, `.venv/`, `*.pyc`)
- Docker相关 (`docker_images/`, `docker_bin/`)

---

## 相关文档

- [CLAUDE.md](./CLAUDE.md) - AI Agent 行为准则
- [README.md](./README.md) - 项目总览和快速开始
- [docs/bastion.md](./docs/bastion.md) - 堡垒机连接方案
- [docs/README.md](./docs/README.md) - 单元测试执行指南
- [PROGRESS.md](./PROGRESS.md) - 总体进度跟踪