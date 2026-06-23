# vLLM修复操作指南

**日期**: 2026-05-29
**目标分支**: `2.5.1_ut_verify`
**环境**: t_h20 (NVIDIA H20-3e), v0.13.0_torch2.5.1_compile容器

> **相关文档**: 历史事故复盘见 [`tasks/ut/docs/incidents/`](../../tasks/ut/docs/incidents/README.md)（含 root cause / 证据链 / 防回归措施，与本指南的"操作动作"互补）。

---

## 一、DeepSeek torch_compile引号修复

**问题**: `deepseek_v2.py:1235` 装饰器缺少引号
```python
# 错误: {input_ids: 0, positions: 0}
# 正确: {"input_ids": 0, "positions": 0}
```

**执行步骤**:
```bash
# 1. 进入容器
sudo docker exec -it v0.13.0_torch2.5.1_compile bash

# 2. 执行修复
python3 -c "
content = open('/gpfs/gcsp/M2.7_verify/vllm/vllm/model_executor/models/deepseek_v2.py').read()
content = content.replace('{input_ids: 0, positions: 0}', '{"input_ids\": 0, \"positions\": 0}')
open('/gpfs/gcsp/M2.7_verify/vllm/vllm/model_executor/models/deepseek_v2.py', 'w').write(content)
print('Fixed!')
"

# 3. 验证修复
grep -n 'support_torch_compile' /gpfs/gcsp/M2.7_verify/vllm/vllm/model_executor/models/deepseek_v2.py

# 4. 清除缓存
find /gpfs/gcsp/M2.7_verify/vllm -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 5. 退出容器
exit
```

---

## 二、提交修复到vllm分支

**目标分支**: `2.5.1_ut_verify`

```bash
# 在t_h20上执行 (容器外或bastion shell)
cd /gpfs/gcsp/M2.7_verify/vllm

# 检查当前分支
git branch
git status

# 如果不在目标分支，切换
git checkout 2.5.1_ut_verify

# 查看修改
git diff vllm/model_executor/models/deepseek_v2.py

# 提交
git add vllm/model_executor/models/deepseek_v2.py
git commit -m "fix: add quotes to DeepSeek torch_compile decorator dynamic_arg_dims

The decorator was missing quotes around dictionary keys:
- Before: {input_ids: 0, positions: 0}
- After: {'input_ids': 0, 'positions': 0}

This fix enables Engine initialization tests to run."
```

---

## 三、运行验证测试

```bash
# 在容器内执行
sudo docker exec -it v0.13.0_torch2.5.1_compile bash

# 测试Engine初始化 (验证DeepSeek修复)
pytest /gpfs/gcsp/M2.7_verify/vllm/tests/engine/test_engine.py -v --tb=short

# 测试samplers目录
pytest /gpfs/gcsp/M2.7_verify/vllm/tests/samplers/ --tb=no -q

# 测试v1目录
pytest /gpfs/gcsp/M2.7_verify/vllm/tests/v1/ --tb=no -q -k "not distributed"
```

---

## 四、其他待修复项

### fp32_precision兼容性 (已修复但需验证)
```bash
# 检查修复状态
grep -A2 'fp32_precision' /gpfs/gcsp/M2.7_verify/vllm/vllm/v1/worker/gpu_worker.py
```

### LoRA类型签名 (已修复)
- 文件: `lora_expand_op.py`, `lora_shrink_op.py`
- 状态: 已提交

---

## 五、Daemon操作

```bash
# Windows本地执行
cd D:/workspace/apmm

# 启动daemon (需要输入OTP)
python agent.py serve t_h20

# 测试连接
python agent.py -p t_h20 ping

# 执行命令
python agent.py -p t_h20 run "hostname"

# 停止daemon
python agent.py -p t_h20 stop
```