# Accuracy Test 评测进度

本目录包含多项基准评测任务。

---

## GPQA-D 评测

### 评测配置

| 项目 | 值 |
|------|-----|
| 模型 | MiniMax-M2.7 |
| API 端口 | 9527 |
| 评测工具 | evalscope |
| 评测数据集 | gsm8k, gpqa_diamond, math_500, ifeval, mmlu_pro, live_code_bench |

### 状态

⏳ 待启动

### 文件

| 文件 | 路径 |
|------|------|
| 评测脚本 | `run_evalscope.sh` |
| 日志目录 | `./log/` |

### 时间记录

- 2026-05-08: 创建评测目录和脚本

---

## Multi-SWE-bench 评测

### 状态

**已暂停** - 2026-05-08

原因：50% 空 patch 问题未解决，准备先在简单数据集上验证推理流程。

详见：`accuracy_test/Multi-SWE/PROGRESS.md`