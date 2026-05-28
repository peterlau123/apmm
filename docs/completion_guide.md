# vLLM单元测试完成指南

**状态**: daemon连接异常，需手动操作完成剩余任务

---

## 一、问题诊断

| 问题 | 状态 | 影响 |
|------|------|------|
| daemon run命令失败 | Socket closed | 无法远程执行测试 |
| DeepSeek装饰器缺少引号 | `{input_ids: 0}` 缺引号 | Engine测试阻塞 |
| 缺失lm_eval模块 | 未安装 | quantization/distributed测试阻塞 |
| 缺失HF模型 | Snowflake等 | 多个测试失败 |

---

## 二、用户需要执行的步骤

### 步骤1: 重启daemon连接
```powershell
# 在PowerShell中执行
python agent.py serve t_h20
# 输入OTP密码

python agent.py serve t_ascend
# 输入OTP密码

# 验证连接
python agent.py -p t_h20 ping
python agent.py -p t_h20 run "ls /gpfs/gcsp/"
```

### 步骤2: 进入容器并修复DeepSeek
```bash
# 进入容器
sudo docker exec -it v0.13.0_torch2.5.1_compile bash

# 修复DeepSeek装饰器引号
cd /gpfs/gcsp/M2.7_verify/vllm/vllm/model_executor/models
python3 << 'EOF'
file = 'deepseek_v2.py'
content = open(file).read()
content = content.replace('{input_ids: 0, positions: 0}', '{"input_ids": 0, "positions": 0}')
open(file, 'w').write(content)
print('DeepSeek decorator fixed!')
EOF

# 清除Python字节码缓存
rm -rf __pycache__
rm -rf /gpfs/gcsp/M2.7_verify/vllm/vllm/v1/worker/__pycache__

# 验证修复成功
python3 -c "from vllm.model_executor.models.deepseek_v2 import DeepseekV2Model; print('Import OK')"
```

### 步骤3: 运行剩余测试目录
```bash
# 在容器内执行
cd /gpfs/gcsp/M2.7_verify/vllm
source ~/.config/vllm_test_env.sh

# 运行Engine相关测试
pytest -v tests/samplers/ --tb=no 2>&1 | tee ut_logs/samplers_final.log
pytest -v tests/detokenizer/ --tb=no 2>&1 | tee ut_logs/detokenizer_final.log
pytest -v tests/v1/ --tb=no 2>&1 | tee ut_logs/v1_final.log
pytest -v tests/entrypoints/ --tb=no 2>&1 | tee ut_logs/entrypoints_final.log
pytest -v tests/lora/ --tb=no 2>&1 | tee ut_logs/lora_final.log

# 运行distributed/quantization测试(需先安装lm_eval)
pytest -v tests/distributed/ --tb=no 2>&1 | tee ut_logs/distributed_final.log
pytest -v tests/quantization/ --tb=no 2>&1 | tee ut_logs/quantization_final.log
```

### 步骤4: 安装缺失依赖 (可选)
```bash
# 在t_ascend上下载lm_eval
python agent.py -p t_ascend run "pip download lm_eval -d /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/"

# 在容器内安装
pip install /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/lm_eval*.whl
```

---

## 三、预期完成后的状态

| 指标 | 当前 | 完成后 |
|------|------|--------|
| 通过测试 | ~700+ | ~1000+ |
| 通过率 | 72% | 85%+ |
| 待运行目录 | 8个 | 0个 |
| 阻塞问题 | 3个 | 已解决 |

---

## 四、完成标准

任务完成条件:
1. 所有可运行的测试目录均已执行
2. DeepSeek修复已应用
3. 测试结果已记录到日志文件
4. PROGRESS.md已更新最终统计

---

请按照上述步骤操作，完成后回复"已完成"，我将检查测试日志并更新最终文档。