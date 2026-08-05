# Phase 2 全量重试完成：test_load 通过率 35.5% → 68%（2026-08-05）

> 场景：run `ut-20260718-164107`（UT Test Workflow v2.2），Phase 1 完成
> （passed=1418 / failed=91 / error=7 / ignored=2484），Phase 2 Stage 1 统计出
> 727 个 timeout batch。本文记录全量重试（15.2h）的最终成果、过程中修复的
> 问题、剩余 ignored 的完整分类。

---

## 1. 执行概况

| 项 | 值 |
|---|---|
| 重试范围 | 727 timeout batch（phase2_stage1_report.json 的 batch_list） |
| 执行方式 | `retry_timeout_batches.py`（v5 单进程调度器 + 动态 GPU 切批） |
| 规模 | **440 super batches**，耗时 **15.2h** |
| 慢测试剔除 | 重试超限（retry>=3）+ XML 实测 >600s 双来源（`retry_slow_tests.json`） |
| 状态 | 719/727 done（8 个 = 7 个纯慢测试 batch + 1 个，故意剔除） |

## 2. 最终成果（test_load 4000 条）

| 状态 | Phase 1 | 重试后 | 变化 |
|---|---|---|---|
| ✅ passed | 1,418 (35.5%) | **2,723 (68.1%)** | **+1,305** |
| ❌ failed | 91 | 225 | +134（真实失败暴露） |
| ⏸️ ignored | 2,484 | **1,044** | **-1,440** |
| ⚠️ error | 7 | 8 | +1 |

`workflow_state.stats` 已通过 `_refresh_stats` 同步（passed=2723 / failed=225 /
ignored=1044 / error=8 / pending=0）。

## 3. 重试结果明细（retry_timeout_summary.json）

- done: 719 batch；重试结果累计 passed=1363 / failed=159 / ignored=975 / error=1
- 重试后 failed 的根因分布（抽样）：
  - **`Server failed to start in time`**（async_tp / attn_quant 等 distributed 测试）：
    vLLM server 启动 241s 超时，Phase 1 时被 batch watchdog 连坐成 timeout，重试后
    暴露为真实 failed
  - assertion 类：数值/逻辑失败

## 4. 剩余 1,044 ignored 的完整分类（已全部查明）

| 类别 | 数量 | 根因 | 可救性 |
|---|---|---|---|
| **kernel 测试**（fused_quant_layernorm 403 / test_cache 391 / prefix_prefill 168） | 962 | 见兼容性报告：**CUDA_VISIBLE_DEVICES 单卡 → 参数化节点 not found** + fused_quant_layernorm **illegal memory access** 崩溃 | ⚠️ 559 个可救（test_cache/prefix_prefill 单独跑全过），403 个真崩 |
| **真慢测试**（sequence_parallelism 48 / attn_quant / shm_broadcast 等） | ~58 | XML 实测 19-60min，watchdog 600s 必杀 | ⚠️ 需 `--timeout 1800` 单跑 |
| 人工过滤 + 其他分布式 | ~24 | `不需要运行，需要被过滤` / GPU 不足 | ❌ 不跑 |

## 5. 过程中修复的问题

| 问题 | 根因 | 修复 commit |
|---|---|---|
| `ignore_reason` 字段名 bug | `update_test_load.py` 写 `ignore_reason`（少个 d），manifest 字段是 `ignored_reason`，16 条历史数据错位 | `d703079` |
| 慢测试剔除机制 | 重试超限用例（retry 5-11 仍 ignored）+ XML 实测 >600s（sequence_parallelism 19-20min）放回队列会连坐同批 | `420a09a` |
| `workflow_state.json.lock` FileNotFoundError | `load_workflow_state` 用 `"r"` 模式读不存在的 lock 文件 | `54bd33b` |
| super_id 撞名 | 8/4 遗留的 batch_super_* 目录 + 遗留全量重试进程与本次并发 | 编号避开 + 清理 48 个遗留目录 |
| Feishu cron 投递失败 | deliver 带 thread（`omt_...`）作 receive_id 校验失败 | 去 thread 发 DM |

## 6. 待优化项

1. **559 个 kernel 测试串行重跑**（test_cache 391 + prefix_prefill 168）：根因是
   execute_batch 设 `CUDA_VISIBLE_DEVICES=单卡` 导致 vllm 参数化只生成 `cuda:0`
   节点，命令行传的 `cuda:1-...` 节点 not found。**不设环境变量单独跑全部
   passed（2.2-2.9s/个）**，串行 ~2h 可救回
2. **58 个真慢测试**：`--timeout 1800` 单跑或接受 ignored
3. **403 个 fused_quant_layernorm**：illegal memory access，需上报 vLLM/H20 兼容性
   （详见兼容性报告）

## 7. 相关文件

- `runs/ut-20260718-164107/retry_timeout_summary.json`（重试汇总）
- `runs/ut-20260718-164107/retry_timeout_progress.json`（增量进度）
- `runs/ut-20260718-164107/retry_slow_tests.json`（慢测试清单）
- `runs/ut-20260718-164107/test_load_4000_20260718_203512.json`（test_load 数据）

---

## 8. 追加：kernel 测试串行重跑（2026-08-05 下午）

使用 `tasks/ut/scripts/retry_kernel_tests.py`（SSH 直连 H20，**不设
CUDA_VISIBLE_DEVICES**，串行单跑），处理 test_cache + prefix_prefill 的
ignored retry=0 用例：

| 项 | 值 |
|---|---|
| 目标 | 556 个（559 - 3 试点；fused_quant_layernorm 403 已排除） |
| 结果 | **passed 315 + skipped 241**（failed=0, error=0），118min |
| skipped 原因 | 代码主动跳过：`Triton implementation only supports NHD layout` 等 |
| test_load 变化 | passed 2723 → **3041**（通过率 68% → **76%**） |

**test_load 最终全量（4000 条）**：passed=3041 / failed=225 / ignored=726 / error=8

剩余 726 ignored 构成（全部有据可查）：
- 241 kernel skipped（pytest 主动跳过，有效结果）
- **403 fused_quant_layernorm（GPU 1 卡硬件异常**——device 参数全固化 cuda:1，
  同一 kernel 在 cuda:0 上全过；非 kernel bug，详见兼容性报告 §2.1）
- 58 真慢测试（sequence_parallelism 19-20min / shm_broadcast 60min）
- 24 人工过滤 + 其他（`不需要运行` / GPU 不足）

*更新时间: 2026-08-05*
