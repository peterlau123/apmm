# vLLM Verify

> **vLLM 推理引擎验证目录**

---

## 目录说明

| 目录 | 说明 |
|------|------|
| **2.5.1/** | vLLM v0.13.0 + PyTorch 2.5.1 验证 |
| **2.5.1/ut/** | 单元测试验证（pytest 测试套件） |

---

## 目录结构

```
vllm/
├── README.md                    # 本文件
└── 2.5.1/                       # vLLM v0.13.0 + PyTorch 2.5.1 验证
    ├── PROGRESS.md              # PyTorch 2.5.1 验证进度
    ├── compile/                 # 编译相关文件
    ├── *.log                    # GPQA-D 评测日志
    └── ut/                      # 单元测试验证
        ├── PROGRESS.md          # UT 详细进度（主入口）
        ├── GOAL.md              # UT 目标
        ├── README.md            # UT 说明
        ├── WORKLOG.md           # UT 工作日志
        ├── docs/                # UT 文档
        │   ├── guides/          # 测试执行指南
        │   ├── reports/         # 测试报告、周报、兼容性分析
        │   └── reference/       # 参考文档
        ├── patches/             # PyTorch 兼容性补丁
        ├── scripts/             # 测试脚本、模型下载脚本
        └── download_test_dependencies.sh
```

---

## 版本信息

### 2.5.1 目录

| 组件 | 版本 |
|------|------|
| vLLM | v0.13.0 |
| PyTorch | 2.5.1+cu124 |
| CUDA | 12.4 |
| Python | 3.12 |
| GPU | NVIDIA H20-3e × 8 |

### ut 目录（单元测试）

| 指标 | 当前状态 |
|------|:--------:|
| 累计通过 | ~2,170 |
| 通过率 | ~99% |
| 覆盖率 | ~22.9% |

详见：[2.5.1/ut/PROGRESS.md](2.5.1/ut/PROGRESS.md)

---

## 主要入口

| 文档 | 位置 | 说明 |
|------|------|------|
| PyTorch 2.5.1 进度 | [2.5.1/PROGRESS.md](2.5.1/PROGRESS.md) | PyTorch 验证进度 |
| UT 详细进度 | [2.5.1/ut/PROGRESS.md](2.5.1/ut/PROGRESS.md) | 单元测试进度（主入口） |
| UT 目标 | [2.5.1/ut/GOAL.md](2.5.1/ut/GOAL.md) | 单元测试目标 |
| UT 文档导航 | [2.5.1/ut/docs/README.md](2.5.1/ut/docs/README.md) | UT 文档中心 |

---

## 测试环境

远程测试路径：`/gpfs/gcsp/M2.7_verify/vllm/tests/`

测试容器：`v0.13.0_torch2.5.1_compile`

---

*更新时间: 2026-06-01*