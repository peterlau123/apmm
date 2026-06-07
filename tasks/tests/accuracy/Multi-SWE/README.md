# Multi-SWE-bench 评测工具集

本目录包含完整的 Multi-SWE-bench 评测工具，用于评估 MiniMax-M2.7 等模型在多语言代码修复任务上的能力。

## 数据集信息

- **名称**: ByteDance-Seed/Multi-SWE-bench
- **来源**: https://multi-swe-bench.github.io
- **实例数**: 1,632 个
- **语言**: 7 种（C, C++, Go, Java, JavaScript, Rust, TypeScript）
- **仓库数**: 约 40 个

## 目录结构

```
Multi-SWE/
├── inference_multi_swe.py          # 推理脚本
├── run_evaluation.sh              # 一键评测脚本
└── README.md                      # 本文档

datasets/
├── Multi-SWE-bench/               # 原始数据集
│   ├── c/                         # C 语言数据
│   ├── cpp/                       # C++ 语言数据
│   ├── go/                        # Go 语言数据
│   ├── java/                      # Java 语言数据
│   ├── js/                        # JavaScript 数据
│   ├── rust/                      # Rust 数据
│   └── ts/                        # TypeScript 数据
│   └── README.md                  # 数据集说明
```

---

## 快速开始

### 一键评测

```bash
bash run_evaluation.sh
```

### 分步执行

**Step 1: 启动 vLLM 服务**

```bash
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 \
    --host 0.0.0.0 \
    --port 8000 \
    --served-model-name MiniMax-M2.7 \
    --max-model-len 8192
```

**Step 2: 运行推理**

```bash
python inference_multi_swe.py \
    --dataset_path /gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench \
    --output_file predictions.jsonl
```

**Step 3: 运行评测**

```bash
python -m multi_swe_bench.harness.run_evaluation --config config.json
```

---

## 完整流程

```
┌───────────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Multi-SWE-bench      │ -> │  vLLM 推理      │ -> │  生成 predictions│
│  (title/body/hints)   │    │  (fix_patch)    │    │  (JSONL)         │
└───────────────────────┘    └─────────────────┘    └─────────────────┘
                                                      │
                                                      v
                                              ┌─────────────────┐
                                              │  Docker 评测    │
                                              │  (运行测试)     │
                                              └─────────────────┘
```

### Step 1: 启动 vLLM 服务

```bash
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 \
    --host 0.0.0.0 \
    --port 8000 \
    --served-model-name MiniMax-M2.7 \
    --max-model-len 8192 \
    --tensor-parallel-size 2  # 如果需要多卡
```

### Step 2: 生成 Predictions

```bash
python inference_multi_swe.py \
    --dataset_path /gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench \
    --output_file ./predictions.jsonl \
    --api_base http://localhost:8000/v1 \
    --model_name MiniMax-M2.7 \
    --temperature 0.2 \
    --max_tokens 4096
```

**可选参数**：

| 参数 | 说明 |
|------|------|
| `--languages rust cpp` | 只处理特定语言 |
| `--max_instances 100` | 限制处理实例数（测试用） |

### Step 3: 准备评测配置

创建评测配置文件 `config.json`：

```json
{
    "mode": "evaluation",
    "workdir": "./data/workdir",
    "patch_files": [
        "./predictions.jsonl"
    ],
    "dataset_files": [
        "/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench/*/*_dataset.jsonl"
    ],
    "force_build": false,
    "output_dir": "./data/output",
    "specifics": [],
    "skips": [],
    "repo_dir": "./data/repos",
    "need_clone": true,
    "global_env": [],
    "clear_env": true,
    "stop_on_error": false,
    "max_workers": 8,
    "max_workers_build_image": 8,
    "max_workers_run_instance": 8,
    "log_dir": "./data/logs",
    "log_level": "INFO"
}
```

### Step 4: 运行评测

```bash
python -m multi_swe_bench.harness.run_evaluation --config config.json
```

### Step 5: 查看结果

结果保存在 `output_dir` 目录：

- `final_report.json`: 总体评测结果
- 各实例运行日志在 `log_dir`

---

## 数据格式

### 输入数据（Multi-SWE-bench）

每个实例包含：

```json
{
    "org": "fmtlib",
    "repo": "fmt",
    "number": 4310,
    "instance_id": "fmtlib__fmt-4310",
    "title": "Add args() accessor back...",
    "body": "Fix #4307...",
    "hints": "Consider using...",
    "fix_patch": "diff --git ...",
    "test_patch": "diff --git ..."
}
```

### 推理输入（Prompt）

从数据生成 prompt：

```
Title: Add args() accessor back...

Description:
Fix #4307...

Hints:
Consider using...

Please generate a patch to fix this issue.
The patch should be in unified diff format.
```

### 输出格式（Predictions）

推理输出需要包含：

```json
{
    "org": "fmtlib",
    "repo": "fmt",
    "number": 4310,
    "fix_patch": "diff --git a/..."
}
```

---

## 按语言评测

### 只评测特定语言

```bash
# 只评测 Rust
python inference_multi_swe.py \
    --languages rust \
    --output_file predictions_rust.jsonl

# 只评测 C++ 和 Rust
python inference_multi_swe.py \
    --languages cpp rust \
    --output_file predictions_cpp_rust.jsonl
```

### 各语言实例数

| 语言 | 实例数 | 主要仓库 |
|------|--------|----------|
| Go | 428 | cli/cli, grpc/grpc-go |
| TypeScript | 224 | vuejs/core, mui/material-ui |
| JavaScript | 357 | sveltejs/svelte, iamkun/dayjs |
| C++ | 129 | nlohmann/json, fmtlib/fmt |
| Rust | 225 | clap-rs/clap, tokio-rs/tokio |
| C | 128 | facebook/zstd, jqlang/jq |
| Java | 125 | fasterxml/jackson-databind |

---

## Docker 镜像

评测使用 Docker 容器运行测试。可选：

1. **预下载镜像**（加速评测）：
   ```bash
   bash scripts/download_images.sh scripts/images_mini.txt
   ```

2. **自动构建镜像**（默认）：评测时自动构建

---

## 与 SWE-bench 的对比

| 特性 | SWE-bench | Multi-SWE-bench |
|------|-----------|------------------|
| **语言** | 仅 Python | 7 种语言 |
| **实例数** | ~2,000 | 1,632 |
| **预处理** | 需要克隆仓库获取代码 | 可直接使用 title/body/hints |
| **评测环境** | Docker | Docker |
| **输出格式** | instance_id + model_patch | org + repo + number + fix_patch |

---

## 常见问题

### vLLM 连接失败

```bash
curl http://localhost:8000/v1/models
```

### Docker 权限问题

```bash
# 确保 Docker 运行
docker ps

# 如果权限不足
sudo usermod -aG docker $USER
```

### 评测失败

检查日志：
```bash
cat ./data/logs/run_evaluation.log
```

---

## 相关资源

| 资源 | 路径 |
|------|------|
| Multi-SWE-bench 工具 | `/gpfs/gcsp/M2.7_verify/tools/multi-swe-bench/` |
| 数据集 | `/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench/` |
| MiniMax 模型 | `/gpfs/gcsp/models/MiniMax-M2.7/` |
| 官方文档 | https://multi-swe-bench.github.io |
| 论文 | https://arxiv.org/abs/2504.02605 |

---

## 总结

本评测流程：

1. ✅ 使用官方数据格式（title + body + hints）
2. ✅ 使用独立推理脚本生成 fix_patch
3. ✅ 使用官方 harness 运行 Docker 评测
4. ✅ 支持按语言筛选评测

**开始评测**：
```bash
# 1. 启动服务
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 --port 8000

# 2. 运行推理
python inference_multi_swe.py --output_file predictions.jsonl

# 3. 运行评测
python -m multi_swe_bench.harness.run_evaluation --config config.json
```