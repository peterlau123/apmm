# GPQA-D 基准评测

本目录包含 MiniMax-M2.7 模型使用 evalscope 进行基准评测的脚本和配置。

## 评测配置

| 项目 | 值 |
|------|------|
| 模型 | MiniMax-M2.7 |
| API 端口 | 9527 |
| 评测工具 | evalscope |
| Eval batch size | 32 |

## 支持的数据集

| 数据集 | 说明 |
|--------|------|
| `gsm8k` | GSM8K 数学题（约 1.3k 题） |
| `gpqa_diamond` | GPQA Diamond 科学问答（约 198 题） |
| `math_500` | MATH-500 数学题（约 500 题） |
| `ifeval` | IFEval 指令遵循评测 |
| `mmlu_pro` | MMLU-Pro 多领域知识评测 |
| `live_code_bench` | LiveCodeBench 代码评测 |

## 使用方法

### 1. 启动 vLLM 服务

在评测节点启动 vLLM 服务：

```bash
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 \
    --port 9527 \
    --host 0.0.0.0 \
    --served-model-name MiniMax-M2.7 \
    --max-model-len 8192 \
    --tensor-parallel-size 2
```

### 2. 运行评测

```bash
cd /gpfs/gcsp/M2.7_verify/accuracy_test/GPQA-D

# 默认使用 gpqa_diamond
bash run_evalscope.sh

# 指定单个数据集
bash run_evalscope.sh gpqa_diamond

# 指定多个数据集
bash run_evalscope.sh gsm8k math_500

# 运行全部数据集
bash run_evalscope.sh all

# 显示帮助
bash run_evalscope.sh --help
```

### 3. 查看结果

评测日志保存在 `./log/` 目录：

```bash
# 查看最新日志
cat ./log/benchmark_evalscope_gpqa_diamond_latest.log

# 查看历史日志
ls -la ./log/
```

## 目录结构

```
GPQA-D/
├── run_evalscope.sh    # 评测脚本
├── README.md           # 本文档
├── PROGRESS.md         # 进度记录
└── log/                # 日志目录
    ├── benchmark_evalscope_<dataset>_latest.log
    └── benchmark_evalscope_<dataset>_<timestamp>.log
```

## 前置要求

- Python 3.10+
- evalscope 已安装：`pip install evalscope`
- vLLM 服务已启动并正常运行

## 安装 evalscope

```bash
pip install evalscope
# 或从源码安装
pip install git+https://github.com/modelscope/evalscope.git
```

## 注意事项

1. 确保 vLLM 服务在评测前已启动并稳定运行
2. 端口 9527 需要可访问
3. 评测可能耗时较长，建议使用 `all` 参数时耐心等待
4. 日志文件会实时写入，可通过 `tail -f` 监控进度

## 相关链接

- [evalscope GitHub](https://github.com/modelscope/evalscope)
- [GPQA Diamond 数据集](https://huggingface.co/datasets/Idavidrein/gpqa)
- [MiniMax-M2.7 模型](https://huggingface.co/MiniMaxAI)