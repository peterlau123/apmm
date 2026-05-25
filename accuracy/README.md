# 精度测试模块

验证 MiniMax-M2.7 模型在各类基准测试上的表现。

---

## 测试项目

| 测试 | 数据集 | 说明 |
|------|--------|------|
| GPQA-Diamond | 198题 | 科学问答，测试专业知识 |
| Multi-SWE-bench | 1632实例 | 多语言代码修复，7种语言 |

---

## 目录结构

```
accuracy/
├── GPQA-D/                 # GPQA-Diamond 评测
│   ├── run_evalscope.sh    # 评测脚本
│   ├── outputs/            # 评测输出结果
│   ├── README.md           # 详细说明
│   └── PROGRESS.md         # 进度记录
├── Multi-SWE/              # Multi-SWE-bench 评测
│   ├── inference_multi_swe.py    # 推理脚本
│   ├── run_minimax_evaluation.sh # 评测脚本
│   ├── README.md           # 详细说明
│   └── PROGRESS.md         # 进度记录
└── PROGRESS.md             # 模块总进度
```

---

## 快速开始

### GPQA-Diamond 评测

```bash
# 1. 启动 vLLM 服务 (在 t_h20)
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 --port 9527 --tensor-parallel-size 2

# 2. 运行评测
cd /gpfs/gcsp/M2.7_verify/accuracy_test/GPQA-D
bash run_evalscope.sh gpqa_diamond
```

### Multi-SWE-bench 评测

```bash
# 1. 启动 vLLM 服务
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 --port 8000

# 2. 运行推理
cd /gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE
python inference_multi_swe.py --output_file predictions.jsonl

# 3. 运行评测
python -m multi_swe_bench.harness.run_evaluation --config config.json
```

---

## 评测工具

### evalscope

支持的评测数据集：
- `gpqa_diamond` - 科学问答
- `gsm8k` - 数学题
- `math_500` - MATH-500
- `ifeval` - 指令遵循
- `mmlu_pro` - 多领域知识
- `live_code_bench` - 代码评测

### Multi-SWE-bench

支持的语言：
- C (128实例)
- C++ (129实例)
- Go (428实例)
- Java (125实例)
- JavaScript (357实例)
- Rust (225实例)
- TypeScript (224实例)

---

## 远程路径

```
/gpfs/gcsp/M2.7_verify/accuracy_test/
```

本地 `accuracy/` 对应远程 `accuracy_test/`。

---

## 相关文档

- [GPQA-D/README.md](./GPQA-D/README.md) - GPQA-Diamond 详细说明
- [Multi-SWE/README.md](./Multi-SWE/README.md) - Multi-SWE-bench 详细说明
- [PROGRESS.md](./PROGRESS.md) - 进度记录