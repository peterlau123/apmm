# vLLM 离线编译模块

> **编译相关文件和进度追踪**

---

## 主要入口

| 文档 | 说明 |
|------|------|
| **[PROGRESS.md](PROGRESS.md)** | 编译进度和问题记录（主入口） |

---

## 目录结构

```
compile/
├── README.md              # 本文件
├── PROGRESS.md            # 编译进度（主入口）
├── CMakeLists.txt         # CMake 配置
├── build_offline.sh       # 离线编译脚本
├── download_build_wheels.sh  # 依赖下载脚本
└── install.log            # 安装日志
```

---

## 版本信息

| 组件 | 版本 |
|------|------|
| vLLM | v0.13.0 |
| PyTorch | 2.5.1+cu124 |
| CUDA | 12.4 |
| Python | 3.12 |
| GPU | NVIDIA H20-3e × 8 |

---

## 编译任务

离线环境编译 vLLM 的步骤：

1. 在联网机器下载依赖包
2. 通过共享存储传输到离线机器
3. 离线安装编译

详见 **[PROGRESS.md](PROGRESS.md)**

---

*更新时间: 2026-06-08*