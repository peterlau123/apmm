# 工作流程说明

本文档说明 vLLM 验证框架的日常工作流程。

---

## 整体流程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   准备阶段   │ ──> │   执行阶段   │ ──> │   分析阶段   │
└─────────────┘     └─────────────┘     └─────────────┘
     │                    │                    │
     ▼                    ▼                    ▼
  启动daemon          运行测试             查看日志
  检查环境            收集结果             更新进度
```

---

## 日常工作流程

### 1. 启动 SSH Daemon

每次 VPN 重连后需要重新启动：

```powershell
# 终端1 - t_h20 (测试机器)
python agent.py serve t_h20
# 输入 OTP 动态密码

# 终端2 - t_ascend (联网机器，如需下载)
python agent.py serve t_ascend
# 输入 OTP 动态密码
```

### 2. 检查环境状态

```powershell
# 检查 daemon 是否存活
python agent.py -p t_h20 ping

# 检查 GPU 状态
python agent.py -p t_h20 run "nvidia-smi"

# 检查容器状态
python agent.py -p t_h20 run "sudo docker ps -a | grep v0.13"

# 检查存储空间
python agent.py -p t_h20 run "df -h | grep gpfs"
```

---

## 单元测试执行流程

### Step 1: 进入测试容器

```powershell
python agent.py -p t_h20 shell
```

然后在远程：

```bash
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
sudo su
cd /gpfs/gcsp/M2.7_verify/vllm
```

### Step 2: 运行测试

```bash
# 单个测试文件
pytest -vv -s tests/test_seed_behavior.py 2>&1 | tee ut_logs/seed_ut.log

# 测试目录 (带过滤)
pytest -vv -s tests/v1/core/ \
    --ignore-glob="**/rocm*" \
    --ignore-glob="**/tpu*" \
    2>&1 | tee ut_logs/core_ut.log
```

### Step 3: 分析结果

```bash
# 查看日志尾部
tail -100 ut_logs/seed_ut.log

# 统计通过/失败
grep -c "PASSED" ut_logs/seed_ut.log
grep -c "FAILED" ut_logs/seed_ut.log
```

---

## 精度评测流程

### Step 1: 启动 vLLM 服务

```bash
vllm serve /gpfs/gcsp/models/MiniMax-M2.7 \
    --port 9527 \
    --host 0.0.0.0 \
    --served-model-name MiniMax-M2.7 \
    --max-model-len 8192 \
    --tensor-parallel-size 2
```

### Step 2: 运行评测

```bash
cd /gpfs/gcsp/M2.7_verify/accuracy_test/GPQA-D
bash run_evalscope.sh gpqa_diamond
```

### Step 3: 查看结果

```bash
cat ./log/benchmark_evalscope_gpqa_diamond_latest.log
```

---

## 依赖下载流程 (离线环境)

### Step 1: 在 t_ascend 下载

```powershell
python agent.py -p t_ascend run "pip download <package> -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/"
```

### Step 2: 在 t_h20 安装

```powershell
python agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_ut pip install /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/<package>.whl"
```

---

## 模型下载流程

### HuggingFace

```powershell
python agent.py -p t_ascend run "huggingface-cli download <model_id> --local-dir /gpfs/gcsp/M2.7_verify/datasets/<model_name>"
```

### ModelScope

```powershell
python agent.py -p t_ascend run "modelscope download --model <model_id> --local_dir /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/modelscope/<model_name>"
```

---

## 进度更新流程

### Step 1: 下载远程日志

```powershell
python agent.py -p t_h20 download /gpfs/gcsp/M2.7_verify/vllm/ut_logs/xxx_ut.log ./vllm_ut_logs/xxx_ut.log
```

### Step 2: 更新 PROGRESS.md

编辑对应的 PROGRESS.md 文件，记录测试结果。

### Step 3: 提交到 Git

```powershell
git add PROGRESS.md
git commit -m "update: xxx test progress"
```

---

## 文件同步流程

### 本地 -> 远程 (上传脚本)

```powershell
python agent.py -p t_h20 upload ./scripts/new_script.py /gpfs/gcsp/M2.7_verify/scripts/new_script.py
```

### 远程 -> 本地 (下载日志)

```powershell
python agent.py -p t_h20 download /gpfs/gcsp/M2.7_verify/vllm/ut_logs/test.log ./logs/test.log
```

---

## 异常处理

### 测试卡住 (等待交互输入)

```powershell
# 发送输入解锁
python agent.py -p t_h20 send "y"

# 或中断命令
python agent.py -p t_h20 cancel
```

### Docker 容器问题

```bash
# 查看容器日志
sudo docker logs v0.13.0_torch2.5.1_ut

# 重启容器
sudo docker restart v0.13.0_torch2.5.1_ut

# 重新进入
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
```

### GPU 内存不足

```bash
# 查看GPU使用情况
nvidia-smi

# 清理缓存
python -c "import torch; torch.cuda.empty_cache()"

# 或重启容器
```