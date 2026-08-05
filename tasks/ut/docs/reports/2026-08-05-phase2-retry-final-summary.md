# Phase 2 重跑最终总结：test_load 通过率 35.5% → 86.1%（2026-08-05）

> 场景：run `ut-20260718-164107`（UT Test Workflow v2.2）。Phase 1 完成
> （passed=1418 / failed=91 / error=7 / ignored=2484），Phase 2 对 727 个
> timeout batch 展开三轮重跑。本文是**最终总结**：三轮重跑全链路、最终
> test_load 状态、剩余 ignored 构成、过程中发现的 4 个问题。

---

## 1. 三轮重跑全链路

| 轮次 | 范围 | 规模 | 结果 | passed 累计 |
|---|---|---|---|---|
| **① 全量重试** | 727 timeout batch（phase2_stage1_report） | 440 super batches / 15.2h | +1,305 passed | 2,723 (68%) |
| **② Kernel 串行重跑** | test_cache 391 + prefix_prefill 168（ignored retry=0） | 556 个 / 118min | +315 passed + 241 skipped（代码主动跳过） | 3,041 (76%) |
| **③ fql device 映射重跑** | fused_quant_layernorm 403（GPU 1 卡异常绕过） | 400 个 / 72min | **+403 全 passed** | **3,444 (86.1%)** |
| **④ 慢测试单跑**（进行中） | sequence_parallelism 48 + attn_quant + shm_broadcast 等 | 58 个 / `--timeout 1800` | 试点 4/4 passed | — |

## 2. 最终数据（test_load 4000 条）

| 状态 | Phase 1 (7/18) | 最终 (8/5) | 变化 |
|---|---|---|---|
| ✅ passed | 1,418 (35.5%) | **3,444 (86.1%)** | **+2,026** |
| ❌ failed | 91 | 225 | +134（真实失败暴露） |
| ⏸️ ignored | 2,484 | **323** | -2,161 |
| ⚠️ error | 7 | 8 | +1 |

`workflow_state.stats` 已同步（pending=0，与 test_load 完全一致）。

## 3. 剩余 323 ignored 构成（全部有据可查）

| 类别 | 数量 | 说明 |
|---|---|---|
| kernel skipped | 241 | pytest 主动跳过（`Triton implementation only supports NHD layout` 等），**有效结果** |
| 真慢测试 | 58 | sequence_parallelism 19-20min / shm_broadcast 60min（第④轮单跑中） |
| 人工过滤 | 24 | `不需要运行，需要被过滤` / GPU 不足 |

## 4. 过程中发现的 4 个问题（全部解决）

| # | 问题 | 根因 | 处置 |
|---|---|---|---|
| 1 | 962 个 kernel 测试误判 ignored | `execute_batch` 设 `CUDA_VISIBLE_DEVICES=单卡` → vllm 参数化只生成 `cuda:0` 节点 → `cuda:1-...` 节点 not found → 收集 0 | 专项脚本不设 env 串行重跑（②）；incident 落档 |
| 2 | 403 个 fused_quant_layernorm illegal memory access | **GPU 1 卡硬件异常**（compute-sanitizer 证实同一 kernel cuda:0 正常/cuda:1 悬垂，非 kernel bug） | device 映射重跑（③）+ execute_batch `exclude_gpus` 配置 |
| 3 | `ignore_reason` 字段名 bug | 写 `ignore_reason`（少个 d），manifest 标准字段 `ignored_reason` | 3 处代码修复 + 16 条数据迁移（commit `d703079`） |
| 4 | `workflow_state.json.lock` 崩溃 | `load_workflow_state` 读不存在的 lock 文件 | 读前 touch（commit `54bd33b`） |

## 5. 交付物

| commit | 内容 |
|---|---|
| `d703079` | ignore_reason → ignored_reason 字段修复 |
| `420a09a` | retry_timeout_batches 慢测试剔除（双来源） |
| `54bd33b` | workflow_state lock 修复 |
| `7c9a0e3` | retry_kernel_tests.py（kernel 串行重跑脚本） |
| `d58c1a7` | 断点续跑支持 |
| `4001fef` | execute_batch `exclude_gpus` + 单元测试 |
| `3fdd876` / `967dc59` / `4a5ad06` / `b1a307f` / `ce776c9` | 报告 + incident + 更正 |

报告与 incident：
- `tasks/ut/docs/reports/2026-08-05-phase2-full-retry-summary.md`（本报告）
- `tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md`
- `tasks/ut/docs/incidents/2026-08-05-kernel-cuda-visible-devices-param-notfound-incident.md`

## 6. 遗留项

1. ~~58 个慢测试单跑~~（第④轮）：**已执行并止损**——见 §7
2. **GPU 1 卡硬件诊断**（`nvidia-smi -r` / 驱动排查 / 换卡）——用户安排

## 7. 追加：慢测试单跑结果（2026-08-05 夜，已止损）

`retry_timeout_batches.py --slow-only --timeout 1800`（新增参数，commit `8adf310`）：

| 项 | 值 |
|---|---|
| 收集 | **~94 个**（xml_prefixes 前缀匹配全部 sequence_parallelism/attn_quant/symm_mem/shm_broadcast 变体，超出预估 58） |
| 已执行 | **64 个 / 14h**：✅ 22 passed / ❌ 37 failed / ⏸️ 5 ignored |
| 止损 | 剩余 ~30 个 sequence_parallelism 未跑（同型失败率 ~58%，收益低，用户决定停止） |
| 回写 | ✅ 53 个 super batch 结果与 test_load 0 差异（全部生效） |

**failed 根因**：`torch.multiprocessing.spawn.ProcessRaisedException`（`init_distributed_environment` 崩溃）——分布式初始化失败，非超时；同文件部分变体通过（222609: 6p/2f），疑似参数化变体/环境 flaky。

**慢的原因**（测试设计使然）：torch.compile 即时编译（每变体独立编译模型 10-20min）+ 2 进程分布式 spawn + 大模型加载（Qwen3-0.6B / Llama-3.1-8B NVFP4）。

**test_load 最终**：passed **3,454（86.4%）** / failed 251 / ignored 287 / error 8
（vs 慢跑前 3,444：+10 passed / +26 failed——慢测试救回部分 + 暴露真实失败）

*更新时间: 2026-08-05*
