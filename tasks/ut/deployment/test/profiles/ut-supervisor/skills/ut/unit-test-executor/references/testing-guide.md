# vLLM单元测试执行指南

> 来源: `tasks/ut/docs/guides/testing.md`

## 项目概述

本项目用于在远程服务器上执行vLLM (v0.13.0) 的单元测试验证。测试环境包含：
- **联网机器 (t_ascend)**: 10.102.234.45 - 用于下载依赖和模型
- **未联网机器 (t_h20)**: 10.10.154.13 - 用于运行测试
- **共享存储**: `/gpfs` (1.9PB) - 两台机器通过此共享数据

## 环境架构

```
本机 (Windows + Git bash)
    │
    │ SSH over Bastion (10.10.192.55:22)
    │ 用户名格式: liuxin/<target_ip>/<role>
    │ 认证: 静态密码 + 动态OTP
    ▼
┌─────────────────────────────────────────────┐
│  t_ascend (10.102.234.45) - 联网            │
│  Profile: t_ascend (daemon_port: 19922)     │
│  - 下载pip包                                │
│  - 下载HuggingFace模型                      │
│  - 存储到 /gpfs/gcsp/M2.7_verify/           │
└─────────────────────────────────────────────┘
                    │
                    │  /gpfs 共享存储 (1.9PB)
                    ▼
┌─────────────────────────────────────────────┐
│  t_h20 (10.10.154.13) - 未联网              │
│  Profile: t_h20 (daemon_port: 19923)        │
│  - Docker容器: v0.13.0_torch2.5.1_compile   │
│  - 运行pytest测试                           │
│  - 日志输出到 ut_logs/                      │
│  - docker路径: /gpfs/gcsp/M2.7_verify/docker_bin/docker │
└─────────────────────────────────────────────┘
```

## Bastion连接方式

### agent.py核心命令

```powershell
# 启动daemon (需输入OTP)
python agent.py serve <profile>

# 检查状态
python agent.py -p <profile> ping

# 执行命令
python agent.py -p <profile> run "command"

# 发送交互命令 (用于进入容器)
python agent.py -p <profile> send "command"

# 进入交互shell
python agent.py -p <profile> shell

# 文件传输
python agent.py -p <profile> upload <local> <remote>
python agent.py -p <profile> download <remote> <local>
```

### 进入测试容器的正确流程

```powershell
# 1. 启动daemon
python agent.py serve t_h20

# 2. 发送命令进入容器
python agent.py -p t_h20 send "sudo docker exec -it v0.13.0_torch2.5.1_compile bash"

# 3. 进入测试目录
python agent.py -p t_h20 send "cd /gpfs/gcsp/M2.7_verify/vllm"

# 4. 运行pytest
python agent.py -p t_h20 send "pytest -vv -s tests/test_xxx.py 2>&1 | tee ut_logs/xxx_<时间戳>.log"
```

**注意**: 
- 正确容器名: `v0.13.0_torch2.5.1_compile`
- pytest路径: `/usr/local/bin/pytest`
- Git bash会自动转换Unix路径，建议用`send`命令而非`run`命令进入容器后执行

## 已知问题

### 缺失Python包

```bash
# 在t_ascend下载
python agent.py -p t_ascend run "pip download <package> -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies"

# 在t_h20容器安装
python agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_compile pip install /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies/<package>.whl"
```

### HuggingFace模型无法访问（未联网环境）

**症状**: `ConnectTimeoutError` 连接 `huggingface.co` 失败
**原因**: t_h20未联网，无法直接访问HF Hub
**解决方案**:
```bash
# 使用已有的本地模型缓存（位于t_ascend）
# 已有模型：opt-125m, distilgpt2, Qwen系列等
export HF_HOME=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
export HF_HUB_CACHE=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub

# 若需下载新模型（在t_ascend执行）
export HF_ENDPOINT=https://hf-mirror.com
python3 -c 'from huggingface_hub import snapshot_download; snapshot_download("gpt2", local_dir="/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub/models--gpt2")'
```

**已有本地模型列表**:
- `facebook/opt-125m` → `models--facebook--opt-125m`
- `distilbert/distilgpt2` → `models--distilbert--distilgpt2`
- `Qwen/Qwen3-0.6B` → `models--Qwen--Qwen3-0.6B`
- 更多见 `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub/hub/`

### 磁盘配额超限

**症状**: `OSError: [Err no 122] Disk quota exceeded`
**原因**: 用户配额限制，而非文件系统空间不足
**解决方案**: 清理旧文件或申请更多配额

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