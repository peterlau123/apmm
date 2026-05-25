# vLLM单元测试执行指南

## 项目概述

本项目用于在远程服务器上执行vLLM (v0.13.0) 的单元测试验证。测试环境包含：
- **联网机器 (t_ascend)**: 10.102.234.45 - 用于下载依赖和模型
- **未联网机器 (t_h20)**: 10.10.154.13 - 用于运行测试
- **共享存储**: `/gpfs` (1.9PB) - 两台机器通过此共享数据

## 环境架构

```
本机 (Windows)
    │
    │ SSH over Bastion (10.10.192.55)
    ▼
┌─────────────────────────────────────────────┐
│  t_ascend (10.102.234.45) - 联网            │
│  - 下载pip包                                │
│  - 下载HuggingFace模型                      │
│  - 存储到 /gpfs/gcsp/M2.7_verify/           │
└─────────────────────────────────────────────┘
                    │
                    │  /gpfs 共享存储
                    ▼
┌─────────────────────────────────────────────┐
│  t_h20 (10.10.154.13) - 未联网              │
│  - Docker容器: v0.13.0_torch2.5.1_ut        │
│  - 运行pytest测试                           │
│  - 日志输出到 ut_logs/                      │
└─────────────────────────────────────────────┘
```

## 快速开始

### Step 1: 启动Daemon连接

在两个终端分别运行：

```powershell
# 终端1 - 联网机器
python agent.py serve t_ascend
# 输入OTP动态密码

# 终端2 - 测试机器
python agent.py serve t_h20
# 输入OTP动态密码
```

### Step 2: 验证连接

```powershell
python agent.py -p t_ascend ping
python agent.py -p t_h20 ping
```

### Step 3: 运行单元测试

进入容器执行测试：

```bash
# 进入容器并切换root
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
sudo su

# 进入vllm目录
cd /gpfs/gcsp/M2.7_verify/vllm

# 运行测试
pytest -vv -s tests/test_xxx.py 2>&1 | tee ut_logs/xxx_ut.log
```

或通过agent.py远程执行：

```powershell
python agent.py -p t_h20 run --timeout 300 "sudo docker exec v0.13.0_torch2.5.1_ut bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv tests/test_seed_behavior.py 2>&1 | tee ut_logs/seed_ut.log'"
```

## 测试过滤规则

运行测试时需排除以下内容：

```bash
pytest tests/ \
    --ignore-glob="tests/**/rocm*" \
    --ignore-glob="tests/**/tpu*" \
    --ignore-glob="tests/**/multimodal*" \
    --ignore-glob="tests/**/nixl*" \
    --ignore-glob="tests/**/ec_connector*" \
    --ignore-glob="tests/**/*image*.py" \
    --ignore-glob="tests/**/*video*.py" \
    --ignore-glob="tests/**/*audio*" \
    --ignore-glob="tests/**/encoder*" \
    --ignore-glob="tests/**/prithvi*" \
    --ignore-glob="tests/models/language/generation/test_gemma.py" \
    --ignore-glob="tests/models/language/generation/test_granite.py" \
    --ignore-glob="tests/models/language/generation/test_hybrid.py" \
    --ignore-glob="tests/models/language/generation/test_mistral.py" \
    --ignore-glob="tests/models/language/generation/test_phimoe.py" \
    --ignore-glob="tests/models/language/generation_ppl_test/*" \
    --ignore-glob="tests/models/language/pooling_mteb_test/*" \
    --ignore-glob="tests/models/language/pooling/*" \
    --ignore-glob="tests/reasoning/test_deepseekr1_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_deepseekv3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_ernie45_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_glm4_moe_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_gptoss_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_granite_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_holo2_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_hunyuan_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_mistral_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_olmo3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_qwen3_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_seedoss_reasoning_parser.py" \
    --ignore-glob="tests/reasoning/test_base_thinking_reasoning_parser.py" \
    -vv -s
```

## 依赖问题处理

### 缺失Python包

```powershell
# 在t_ascend下载
python agent.py -p t_ascend run "pip download <package> -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/"

# 在t_h20容器安装
python agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_ut pip install /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/<package>.whl"
```

### 缺失HuggingFace模型

```powershell
# 在t_ascend下载模型
python agent.py -p t_ascend run "huggingface-cli download <model_id> --local-dir /gpfs/gcsp/M2.7_verify/datasets/<model_name>"

# 测试时使用本地路径或设置环境变量
export HF_HOME=/gpfs/gcsp/M2.7_verify/datasets
export TRANSFORMERS_CACHE=/gpfs/gcsp/M2.7_verify/datasets
```

## 测试进度跟踪

### 已完成的测试
| 日志文件 | 测试范围 | 状态 |
|---------|---------|------|
| basic_ut.log | tests/basic_correctness/ | ✅ |
| config_ut.log | tests/test_config.py | ✅ |
| core_ut.log | tests/v1/core/ | ✅ |
| input_ut.log | tests/test_inputs.py | ✅ |
| output_ut.log | tests/test_outputs.py | ✅ |

### 待运行的测试
详见 `docs/test_statistics.md`

## 文件结构

```
D:\workspace\apmm\
├── agent.py              # SSH代理脚本 (堡垒机连接)
├── .bastion_creds        # 连接凭据配置
├── docs/
│   ├── bastion.md        # 堡垒机连接方案说明
│   ├── test_statistics.md # 测试统计报告
│   └── README.md         # 本文件
└── CLAUDE.md             # 项目说明
```

远程目录 `/gpfs/gcsp/M2.7_verify/`:
```
/gpfs/gcsp/M2.7_verify/
├── vllm/                 # vLLM源码 (v0.13.0)
│   ├── tests/            # 测试文件
│   ├── ut_logs/          # 测试日志输出
│   └── vllm/             # vLLM包
├── pytorch_verify/       # PyTorch验证
│   └── 2.5.1/ut/         # 下载的依赖包
├── datasets/             # HuggingFace模型缓存
└── .venv/                # Python虚拟环境
```

## 常用命令

```powershell
# 检查daemon状态
python agent.py -p t_ascend ping
python agent.py -p t_h20 ping

# 查看远程目录
python agent.py -p t_ascend run "ls /gpfs/gcsp/M2.7_verify/vllm/"

# 查看测试日志
python agent.py -p t_ascend run "cat /gpfs/gcsp/M2.7_verify/vllm/ut_logs/config_ut.log | tail -50"

# 检查GPU状态
python agent.py -p t_h20 run "nvidia-smi"

# 检查容器状态
python agent.py -p t_h20 run "sudo docker ps -a | grep v0.13"
```

## 已知问题

### LoRA导入错误
```
ValueError: infer_schema(func): Parameter lora_a_stacked has unsupported type list[torch.Tensor]
```
原因: PyTorch版本与类型签名不兼容，需检查容器内PyTorch版本

### Triton导入失败
```
No module named 'triton.language.target_info'
```
原因: Triton版本兼容性问题

### HuggingFace模型无法访问
原因: 未联网机器无法访问HF Hub，需预先下载模型到共享存储