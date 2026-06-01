# 单元测试模块

运行 vLLM pytest 测试套件。

---

## 主要入口

| 文档 | 说明 |
|------|------|
| **[PROGRESS.md](PROGRESS.md)** | UT详细进度（主入口） |
| **[GOAL.md](GOAL.md)** | 单元测试目标 |
| **[WORKLOG.md](WORKLOG.md)** | 每日工作日志 |
| **[docs/README.md](docs/README.md)** | UT文档导航 |

---

## 测试范围

| 类别 | 文件数 | 说明 |
|------|--------|------|
| tests根目录 | 13 | 基础测试 |
| 子目录 | 30 | 模块测试 |
| 已排除 | ~246 | 不支持的平台/模型 |

---

## 目录结构

```
unit_test/
├── PROGRESS.md          # UT详细进度（主入口）
├── GOAL.md              # UT目标
├── WORKLOG.md           # UT工作日志
├── README.md            # 本文件
│
└── docs/                # UT专用文档
    ├── README.md        # 文档导航
    ├── guides/          # 测试执行指南
    ├── reports/         # 测试报告、周报、兼容性分析
    └── reference/       # UT参考文档
```

远程测试文件位于：
```
/gpfs/gcsp/M2.7_verify/vllm/tests/
```

---

## 测试排除规则

不支持的平台和功能：

```bash
# 平台排除
--ignore-glob="tests/**/rocm*"     # AMD GPU
--ignore-glob="tests/**/tpu*"      # TPU

# 功能排除
--ignore-glob="tests/**/multimodal*"  # 多模态
--ignore-glob="tests/**/nixl*"        # NVIDIA传输库
--ignore-glob="tests/**/ec_connector*" # 外部连接器

# 文件排除
--ignore-glob="tests/**/*image*.py"
--ignore-glob="tests/**/*video*.py"
--ignore-glob="tests/**/*audio*.py"
--ignore-glob="tests/**/encoder*"
--ignore-glob="tests/**/prithvi*"
```

---

## 运行测试

详见 **[docs/guides/testing.md](docs/guides/testing.md)** - 测试执行指南

---

## 当前进度统计

| 指标 | 数量 |
|------|:----:|
| ✅ 累计通过 | ~2,170 |
| ❌ 累计失败 | ~160 |
| 通过率 | ~99% |
| 覆盖率 | ~22.9% |

---

*更新时间: 2026-06-01*