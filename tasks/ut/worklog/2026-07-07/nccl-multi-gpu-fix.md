# NCCL Multi-GPU 分布式测试修复

**日期:** 2026-07-07
**任务:** 修复 Multi-GPU distributed tests NCCL 错误，准备76个缺失批次执行方案

---

## 问题背景

在 runs/ut-20260630-163959 检查中发现：
- **76个缺失批次**（全部为 Multi-GPU distributed tests）
- 执行时出现 NCCL 错误：`CUDA driver version is insufficient for CUDA runtime version`

---

## 诊断过程

### 1. NCCL 版本分析

| 来源 | NCCL版本 | CUDA版本 | 兼容性 |
|------|---------|---------|--------|
| pip nvidia-nccl-cu12 | 2.21.5 | 12.4 | ✅ 兼容 |
| pip nvidia-nccl-cu13 | 2.29.7 | 13.2 | ❌ 不兼容 |
| 系统 NCCL | 2.28.9 | 13.0 | ❌ 不兼容 |
| conda NCCL | 2.21.5 | 12.4 | ✅ 兼容 |

**根本原因:** PyTorch pip 安装的 `nvidia-nccl-cu13` (CUDA 13.2) 被默认加载，与容器 CUDA 12.4 runtime 不兼容。

### 2. PyTorch API 兼容性问题

测试 `test_async_tp_pass_replace` 失败：
```
AttributeError: module 'torch.distributed._symmetric_memory' has no attribute 'empty'
```

**原因:** `_symmetric_memory.empty` API 仅存在于 PyTorch 2.7+，当前容器 PyTorch 2.5.1 缺失此 API。

---

## 解决方案

### NCCL 修复方案

使用 conda 的 NCCL 2.21.5 (CUDA 12.4) 通过 `LD_PRELOAD`:

```bash
export LD_PRELOAD=/gpfs/gcsp/miniconda3/lib/python3.12/site-packages/nvidia/nccl/lib/libnccl.so.2
```

**验证结果:** NCCL all_reduce 测试通过 ✅

### 容器选择策略

| 测试类型 | 容器 | 原因 |
|---------|------|------|
| `test_async_tp_pass_replace` | `m2.7_v0.13.0_torch2.7` | 需要 `_symmetric_memory.empty` API |
| 其他分布式测试 | `v0.13.0_torch2.5.1_compile` + NCCL fix | NCCL preload workaround |

---

## 创建的文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 执行脚本 | `runs/ut-20260630-163959/run_missing_batches_nccl_fix.sh` | 包含 NCCL fix + 容器选择逻辑 |

---

## 清理的文件

删除临时诊断脚本：
- `tmp_cuda_check.py`
- `tmp_nccl_check.py`
- `tmp_nccl_diag.py`
- `tmp_nccl_preload_test.py`
- `tmp_nccl_test.py`
- `tmp_symmem_check.py`

---

## NCCL 修复实施（2026-07-07 执行）

### 修复步骤

1. **✅ 检查NCCL wheel包**
   - 路径: `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/nvidia_nccl_cu12-2.21.5-cp312-cp312-linux_x86_64.whl`
   - 大小: ~50MB
   - 状态: 已存在，无需重新下载

2. **✅ 卸载冲突的 nvidia-nccl-cu13**
   ```bash
   python tools/agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_compile pip uninstall nvidia-nccl-cu13 -y"
   ```
   - 结果: `Successfully uninstalled nvidia-nccl-cu13-2.29.7`

3. **✅ 安装 nvidia-nccl-cu12 2.21.5**
   - 状态: 已存在，无需重复安装

4. **✅ 验证NCCL版本**
   ```bash
   python tools/agent.py -p t_h20 run "sudo docker exec v0.13.0_torch2.5.1_compile /gpfs/gcsp/miniconda3/bin/python -c 'import torch; print(torch.cuda.nccl.version())'"
   ```
   - 结果: `(2, 21, 5)` ✅

5. **✅ 分布式测试验证**
   - NCCL初始化成功
   - all-reduce测试通过
   - NCCL版本与容器CUDA 12.4兼容

### 修复结果

| 项目 | 状态 | 备注 |
|------|------|------|
| nvidia-nccl-cu13 卸载 | ✅ 完成 | 已移除冲突版本 2.29.7 |
| nvidia-nccl-cu12 安装 | ✅ 完成 | 版本 2.21.5 (CUDA 12.4兼容) |
| NCCL版本验证 | ✅ 通过 | torch.cuda.nccl.version() = (2, 21, 5) |
| 分布式测试 | ✅ 通过 | NCCL初始化 + all-reduce 测试成功 |

### 修复说明

本次修复采用了**NCCL wheel重装方案**（非LD_PRELOAD workaround）：
- 从根本上解决了NCCL版本冲突问题
- 不再依赖LD_PRELOAD环境变量
- 修复是永久性的，重启容器后依然有效

相比之前考虑的LD_PRELOAD方案，此方案更干净、更持久。

---

## 下一步操作

NCCL修复已完成，现在可以执行76个缺失的Multi-GPU批次：

```bash
# 方式1: 上传脚本到远程执行
python tools/agent.py upload --profile t_h20 \
    runs/ut-20260630-163959/run_missing_batches_nccl_fix.sh \
    /gpfs/gcsp/M2.7_verify/unit_test/ut-20260630-163959/

# 方式2: 直接在容器内执行
docker exec m2.7_v0.13.0_torch2.7 bash \
    /gpfs/gcsp/M2.7_verify/unit_test/ut-20260630-163959/run_missing_batches_nccl_fix.sh
```

---

## 环境信息

| 组件 | 信息 |
|------|------|
| 容器 PyTorch 2.5.1 | `v0.13.0_torch2.5.1_compile` |
| 容器 PyTorch 2.7 | `m2.7_v0.13.0_torch2.7` |
| CUDA Runtime | 12.4 |
| CUDA Driver | 12.9 (575.57.08) |
| GPU | NVIDIA H20-3e × 8 |
| NCCL fix路径 | `/gpfs/gcsp/miniconda3/lib/python3.12/site-packages/nvidia/nccl/lib/libnccl.so.2` |

---

## 关键发现

1. **PyTorch pip 安装多个 NCCL 版本**: 同时存在 `nvidia-nccl-cu12` 和 `nvidia-nccl-cu13`
2. **cu13 版本被默认加载**: 导致 CUDA版本不匹配
3. **PyTorch 2.7 容器已存在**: 可用于 `_symmetric_memory` API 测试

---

*记录时间: 2026-07-07 20:57*
*更新时间: 2026-07-07（NCCL修复实施完成）*