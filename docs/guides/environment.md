# 环境配置说明

本文档详细说明 vLLM 验证框架的环境配置。

---

## 服务器配置

### t_ascend (联网机器)

| 配置项 | 值 |
|--------|-----|
| IP | 10.250.121.21 |
| 用户 | infra |
| 存储 | 本地 NVMe 1.8TB |
| 用途 | 下载依赖、模型 |
| GPU | 无 |
| /gpfs | 无挂载 |

### t_h20 (测试机器)

| 配置项 | 值 |
|--------|-----|
| IP | 10.10.154.13 |
| 用户 | infra |
| 存储 | /gpfs 共享存储 1.9PB (85%已用) |
| 用途 | 运行测试、Docker容器 |
| GPU | NVIDIA H20-3e × 8 (143GB显存/卡) |
| CUDA | 12.4 |

### 堡垒机

| 配置项 | 值 |
|--------|-----|
| IP | 10.10.192.55 |
| 端口 | 22 |
| 系统 | 治 Shterm v3.3.13 |

---

## Docker 容器

### 运行中的容器

```bash
sudo docker ps -a
```

| 容器名 | 镜像 | 用途 | 状态 |
|--------|------|------|------|
| `v0.13.0_torch2.5.1_ut` | vllm/vllm-openai:v0.13.0 | 单元测试 | Up 13 days |
| `v0.13.0_torch2.5.1_compile` | vllm/vllm-openai:v0.13.0 | 编译测试 | Up 2 weeks |
| `m2.7_v0.13.0_evalscope` | evalscope_tools:0312 | 精度评测 | Up 2 weeks |
| `m2.7_v0.13.0_port7777` | vllm/vllm-openai:v0.13.0 | vLLM服务 | Up 2 weeks |
| `m2.7_v0.13.0_torch2.7` | vllm/vllm-openai:v0.13.0 | PyTorch 2.7 | Up 2 weeks |

### 进入容器

```bash
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
sudo su
cd /gpfs/gcsp/M2.7_verify/vllm
```

### vLLM UT/compile 容器启动命令

`v0.13.0_torch2.5.1_compile` 使用 `--init` 启动，PID 1 为 `docker-init`，用于信号转发和 zombie 进程回收。当前容器镜像已备份到 `/gpfs/gcsp/M2.7_verify/docker_images/`。

```bash
sudo docker run -d -t --init \
  --net=host --uts=host --ipc=host \
  --privileged=true --group-add video \
  --shm-size 100gb --ulimit memlock=-1 \
  --memory=500g --memory-swap=1000g \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --device=/dev/dri \
  --device=/dev/infiniband \
  --gpus all \
  -v /gpfs:/gpfs \
  --name v0.13.0_torch2.5.1_compile \
  --entrypoint /bin/bash \
  v0.13.0_torch2.5.1_compile:backup-20260616-142616
```

`docker exec` 启动的 pytest 进程仍可能成为 session leader；对应兼容补丁见 `tasks/ut/patches/setpgrp_compat.patch`。

---

## 共享存储路径

```
/gpfs/gcsp/M2.7_verify/
├── vllm/                    # vLLM 源码 (v0.13.0)
│   ├── tests/               # 测试文件
│   ├── vllm/                # vLLM 包
│   └── ut_logs/             # 测试日志输出
├── pytorch_verify/          # PyTorch 验证
│   ├── pytorch/             # PyTorch 源码
│   ├── 2.5.1/               # PyTorch 2.5.1 评测日志
│   ├── 2.7.0/               # PyTorch 2.7.0 评测日志
│   └── *_torch_packages/    # 预下载 wheel 包
├── datasets/                # HuggingFace 模型缓存
├── models/                  # MiniMax-M2.7 等模型
├── tools/                   # 评测工具
├── accuracy_test/           # 精度测试
├── feature_test/            # 功能测试
├── performance_test/        # 性能测试
├── unit_test/               # 单元测试
└── .venv/                   # Python 虚拟环境
```

---

## Python 环境

### 虚拟环境

```bash
# 使用 uv 创建环境
uv venv --python 3.12
source .venv/bin/activate

# 安装 vLLM (开发模式)
VLLM_USE_PRECOMPILED=1 uv pip install -e . --torch-backend=auto
```

### 依赖版本

| 包 | 版本 |
|----|------|
| torch | 2.5.1+cu124 或 2.7.0+cu128 |
| vllm | 0.13.0 |
| triton | 3.x |
| transformers | latest |
| pytest | 8.x |

### 依赖安装 (离线环境)

```bash
# 在 t_ascend 下载
pip download <package> -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/

# 在 t_h20 容器安装
pip install /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/<package>.whl
```

---

## 模型路径

### MiniMax-M2.7

```bash
/gpfs/gcsp/models/MiniMax-M2.7/
```

### HuggingFace 缓存

```bash
# 环境变量设置
export HF_HOME=/gpfs/gcsp/M2.7_verify/datasets
export TRANSFORMERS_CACHE=/gpfs/gcsp/M2.7_verify/datasets
```

### ModelScope 缓存

```bash
export MODELSCOPE_CACHE=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/modelscope
```

---

## 网络端口

### 本地 Daemon 端口

| Profile | 端口 | 目标服务器 |
|---------|------|-----------|
| t_ascend | 19922 | 10.250.121.21 |
| t_h20 | 19923 | 10.10.154.13 |

### vLLM 服务端口

| 服务 | 端口 | 用途 |
|------|------|------|
| vLLM serve | 7777 | 模型推理服务 |
| vLLM serve | 9527 | 精度评测服务 |

---

## 常用命令

### 检查 GPU

```bash
nvidia-smi
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
```

### 检查存储

```bash
df -h | grep gpfs
du -sh /gpfs/gcsp/M2.7_verify/*
```

### 检查 Docker

```bash
sudo docker ps -a
sudo docker images
sudo docker logs <container_name>
```