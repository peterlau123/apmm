# PyTorch Verify

本目录用于 PyTorch 多版本验证和评测环境管理。

## 目录结构

```
pytorch_verify/
├── pytorch/                    # PyTorch 源代码仓库
│   ├── torch/                  # PyTorch Python 包
│   ├── aten/                   # ATen 张量库
│   ├── csrc/                   # C++ 源码
│   ├── test/                   # 测试套件
│   └── ...                     # 其他组件
├── 2.5.1/                      # PyTorch 2.5.1 评测日志
├── 2.5.1_torch_packages/       # PyTorch 2.5.1 wheel 包（CUDA 12.4）
├── 2.6.0/                      # PyTorch 2.6.0 评测日志
├── 2.6.0_torch_packages/       # PyTorch 2.6.0 wheel 包（CUDA 12.6）
├── 2.7.0/                      # PyTorch 2.7.0 评测日志
├── 2.7.0_torch_packages/       # PyTorch 2.7.0 wheel 包（CUDA 12.8）
├── 2.8.0/                      # PyTorch 2.8.0 评测日志
├── 2.8.0_torch_packages/       # PyTorch 2.8.0 wheel 包（CUDA 12.9）
└── README.md                   # 本文档
```

## PyTorch 版本信息

| 版本 | CUDA 版本 | Python 版本 | 状态 |
|------|-----------|-------------|------|
| 2.5.1 | CUDA 12.4 | cp312 | ✅ 可用 |
| 2.6.0 | CUDA 12.6 | cp312 | ✅ 可用 |
| 2.7.0 | CUDA 12.8 | cp312 | ✅ 可用 |
| 2.8.0 | CUDA 12.9 | cp312 | ✅ 可用 |

## 预下载的 Wheel 包

每个版本的 `*_torch_packages/` 目录包含：

| 包名 | 说明 |
|------|------|
| `torch-*.whl` | PyTorch 核心 |
| `torchvision-*.whl` | TorchVision 图像处理 |
| `torchaudio-*.whl` | TorchAudio 音频处理 |
| `triton-*.whl` | Triton 编译器 |
| `nvidia_*.whl` | NVIDIA CUDA 相关库 |

## 安装 PyTorch

### 方法 1：使用预下载的 wheel 包

```bash
# 进入对应版本目录
cd /gpfs/gcsp/M2.7_verify/pytorch_verify/2.7.0_torch_packages/

# 安装所有 wheel 包
pip install *.whl

# 或选择性安装
pip install torch-2.7.0+cu128-cp312-cp312-manylinux_2_28_x86_64.whl
pip install torchvision-0.22.0+cu128-cp312-cp312-manylinux_2_28_x86_64.whl
pip install torchaudio-2.7.0+cu128-cp312-cp312-manylinux_2_28_x86_64.whl
```

### 方法 2：从 PyTorch 源码安装

```bash
cd /gpfs/gcsp/M2.7_verify/pytorch_verify/pytorch/

# 创建虚拟环境
uv venv --python 3.12
source .venv/bin/activate

# 开发模式安装
VLLM_USE_PRECOMPILED=1 uv pip install -e . --torch-backend=auto
```

## 运行 PyTorch 测试

```bash
cd /gpfs/gcsp/M2.7_verify/pytorch_verify/pytorch/

# 运行单个测试
.venv/bin/python -m pytest tests/test_torch.py -v

# 运行特定模块测试
.venv/bin/python -m pytest tests/nn/test_nn.py -v

# 运行 CUDA 测试
.venv/bin/python -m pytest tests/cuda/test_cuda.py -v
```

## 评测日志

各版本目录下的日志文件：

- `2.7.0/gpqa-d.log` - GPQA-Diamond 评测日志
- `2.7.0/multi-swe.log` - Multi-SWE-bench 评测日志

## CUDA 版本兼容性

| CUDA 版本 | PyTorch 版本 | NVIDIA Driver 要求 |
|-----------|--------------|-------------------|
| CUDA 12.4 | 2.5.1 | ≥ 525.60.13 |
| CUDA 12.6 | 2.6.0 | ≥ 525.60.13 |
| CUDA 12.8 | 2.7.0 | ≥ 525.60.13 |
| CUDA 12.9 | 2.8.0 | ≥ 525.60.13 |

## 相关链接

- [PyTorch 官网](https://pytorch.org/)
- [PyTorch GitHub](https://github.com/pytorch/pytorch)
- [PyTorch 文档](https://pytorch.org/docs/)
- [CUDA 版本兼容性](https://pytorch.org/get-started/previous-versions/)

## 注意事项

1. 确保 NVIDIA Driver 版本与 CUDA 版本兼容
2. Python 版本推荐 3.12（cp312）
3. wheel 包已预下载，无需联网即可安装
4. 评测日志保存在对应版本目录下