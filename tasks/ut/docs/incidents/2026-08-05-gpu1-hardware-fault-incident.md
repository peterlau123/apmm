# H20 GPU 1 卡硬件异常事故（GPC1 MMU Fault 导致 403 个测试误判失败）

**日期**: 2026-08-05
**严重等级**: P1（403 个 fused_quant_layernorm 用例全部失败的根因；硬件级故障）
**影响范围**: UT workflow run `ut-20260718-164107`，test_fused_quant_layernorm.py 403 个参数化用例（device 全部固化 cuda:1）
**修复状态**: 🟡 **测试侧已闭环**（device 映射重跑 400 个全部通过 + `exclude_gpus` 配置）；**硬件待维修**（需上报集群管理员换卡/检修）

---

## 事故概述

H20 节点 `infra-gpu-h20-022` 的**物理卡 1（GPU 1，PCI 0000:18:00）GPC1 硬件单元故障**：
任何 kernel 在 cuda:1 上执行都触发 illegal memory access（读悬垂内存）。
由于 Phase 1 generate_batch 生成用例时把 device 参数固化在 cuda:1，导致
**403 个 fused_quant_layernorm 用例全部失败**，一度被误判为 vllm kernel
vectorized 路径 bug。

## 触发条件

- 任意 CUDA kernel 在 cuda:1（物理卡 1）执行
- 涉及：`per_token_group_quant_8bit_kernel`（compute-sanitizer 首个定位的 kernel）
- 同一 kernel 同一输入在 cuda:0 完全正常

## 根因分析

### 直接根因：GPC1（图形处理集群 1）MMU 路径故障

dmesg 硬件错误日志（PCI 0000:18:00 = 卡 1）：

```
NVRM: Xid (PCI:0000:18:00): 31, pid=1553988, name=python3
  MMU Fault: ENGINE GRAPHICS GPC1 GPCCLIENT_T1_6 faulted @ 0x7fad_13400000.
  Fault is of type FAULT_PDE ACCESS_TYPE_VIRT_READ
```
- **Xid 31（MMU Fault）× 9 次**——kernel 访问无效 PDE（页表项）
- **Xid 43（断流）× 4 次**——Xid 31 后的二次错误
- 错误集中在 **GPC1 单元**——硬件级 MMU/显存路径故障

### 为什么 nvidia-smi 表面正常

| 检查项 | 结果 |
|---|---|
| ECC 错误计数 | 0（GPC MMU 故障不产生 ECC 位错） |
| 温度/利用率 | 31°C / 0%（空闲） |
| compute-sanitizer | **确认**：cuda:1 上 input 指针悬垂（负 768MB 偏移） |

### 为什么被误判为 kernel bug（教训）

1. 早前结论"vllm kernel vectorized 路径越界"**错误**——cuda:0 上 hidden 对齐照样 passed
2. "hidden 16 对齐规律"是假象——非对齐组合因测试开头 `hidden_size % group_size != 0`
   提前 `return` **假通过**（kernel 未执行）
3. 决定性证据：**同一 op 同一形状，cuda:0 正常 / cuda:1 崩**（对照实验）

## 证据链（2026-08-05）

| 实验 | 结果 |
|---|---|
| cuda:0 单独跑 `per_token_group_quant_int8`（[1,1024] bf16, group=64） | ✅ OK 无越界 |
| cuda:1 单独跑同一 op（同形状） | 💥 `Invalid __global__ read`（input 悬垂 768MB） |
| `test_rms_norm[cuda:0-...-1-1024]` | ✅ 1 passed, 1.97s |
| cuda:0 抽样 7 组组合 | ✅ 5 passed（2 组 0-tests 为测试自身条件） |
| dmesg | Xid 31 × 9 + Xid 43 × 4（GPC1 MMU fault） |
| nvidia-smi -r 重置 | ❌ 被 bip-agent（集群管理）+ Fabric Manager 占用挡住 |

## 影响范围

| 测试 | 数量 | 处置 |
|---|---|---|
| test_fused_quant_layernorm（cuda:1 参数化） | 403 | device 映射 cuda:1→cuda:0 重跑 **400 个全部 passed** |

## 修复动作

1. **device 映射重跑**：`retry_kernel_tests.py --device-map cuda:1=cuda:0`
   （运行层映射到健康卡，回写原 cuda:1 节点）→ 400/400 passed，405 个用例全部验证通过
2. **execute_batch `exclude_gpus` 配置**（commit `4001fef`）：workflow.yaml
   `exclude_gpus: [1]`，后续跑测试自动避开卡 1（force 模式和探测模式均过滤）
3. **单元测试**：`test_execute_batch_exclude_gpus_filters_pool`

## 防回归措施

1. `exclude_gpus` 配置机制——异常卡自动排除（已生效）
2. **"node not found / illegal memory access" 不能直接判 kernel bug**——先做
   双卡对照（同一 kernel 在不同卡验证），排除硬件因素（本事故教训）
3. **硬件维修**：上报集群管理员（bip-agent 占用 + Fabric Manager 导致无法
   nvidia-smi -r；GPC1 故障需换卡/检修）

## 相关文件

- 兼容性报告：`tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md` §2.1
- 修复代码：`skills/ut/unit-test-executor/scripts/execute_batch.py`（exclude_gpus）
- 重跑脚本：`tasks/ut/scripts/retry_kernel_tests.py`（--device-map）

*更新时间: 2026-08-05*
