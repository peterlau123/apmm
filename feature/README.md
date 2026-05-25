# 功能测试模块

验证 vLLM 各版本的核心功能。

---

## 测试版本

| 版本 | 说明 | 状态 |
|------|------|------|
| v0.11.1 | 基础功能验证 | 待开始 |
| v0.13.0 | 主验证版本 | 进行中 |
| v0.17.0 | 最新版本验证 | 待开始 |
| latest | 当前最新 | 待开始 |
| vllm_test | 通用功能测试 | 待开始 |

---

## 目录结构

```
feature/
├── v0.11.1/                # vLLM v0.11.1 功能验证
├── v0.13.0/                # vLLM v0.13.0 功能验证
│   ├── run_qwen3_0.6B.py   # Qwen3-0.6B 测试脚本
│   └── test_input_optimized.json
│   └── test_output_optimized.json
├── v0.17.0/                # vLLM v0.17.0 功能验证
├── latest/                 # 最新版本验证
├── vllm_test/              # 通用功能测试
│   ├── vllm_function_test.py
│   └── test_input_template.json
└── PROGRESS.md             # 进度记录 (待创建)
```

---

## 测试内容

### 核心功能

- 模型加载与推理
- OpenAI API 兼容性
- 流式输出
- 多卡并行 (Tensor Parallel)
- 量化支持
- LoRA 支持

### API 测试

- `/v1/completions`
- `/v1/chat/completions`
- `/v1/models`
- `/health`

---

## 快速开始

### 运行功能测试

```bash
cd /gpfs/gcsp/M2.7_verify/feature_test/v0.13.0
python run_qwen3_0.6B.py
```

### API 测试

```bash
# 启动 vLLM 服务
vllm serve /gpfs/gcsp/models/Qwen3-0.6B --port 8000

# 测试 API
curl http://localhost:8000/v1/models
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen3-0.6B", "messages": [{"role": "user", "content": "Hello"}]}'
```

---

## 远程路径

```
/gpfs/gcsp/M2.7_verify/feature_test/
```

本地 `feature/` 对应远程 `feature_test/`。

---

## 相关文档

- [PROGRESS.md](./PROGRESS.md) - 进度记录