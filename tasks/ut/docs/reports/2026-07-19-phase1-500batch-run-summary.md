# UT Workflow Phase 1 运行总结报告

**运行ID**: ut-20260718-164107
**报告时间**: 2026-07-19（最终更新）
**策略**: two-phase（terminal-workflow + 生产环境）
**Phase**: Phase 1（全量执行，**已完成**）

---

## 1. 运行概况

| 项 | 值 |
|---|---|
| run 目录 | `runs/ut-20260718-164107` |
| manifest | 32933 测试（重新生成 + 合并旧状态，详见 incident 文档） |
| test_load | 4000 测试（500 batch × batch_size=8） |
| batch_size | 8 |
| gpu_per_test | 2（distributed）/ 1（normal） |
| GPU 策略 | 动态探测，显存占用 < 50% 视为空闲 |
| wall_timeout | 300s / 测试 |
| 启动时间 | 2026-07-18 21:35 |
| 完成时间 | 2026-07-19 22:26 |
| **总耗时** | **~25 小时**（跨多轮，含通道中断 + bug 修复） |

### Batch 执行结果（最终）

| 指标 | 值 |
|------|-----|
| 总 batch | 1384 |
| successful | 1380 |
| failed | 4 |
| **batch 成功率** | **99.71%** |
| **test_load 处理率** | **4000/4000 = 100%** |

---

## 2. 测试结果分布（test_load 4000，最终）

| 状态 | 数量 | 占比 | 说明 |
|------|------|------|------|
| passed | 1418 | 35.5% | 测试通过 |
| failed | 91 | 2.3% | 断言失败（实际多为网络错误，见 §4） |
| error | 12 | 0.3% | collection/import 错误 |
| ignored | 2479 | 62.0% | 超时/无结果 |
| pending | **0** | 0% | **全部跑完** |
| **已处理** | **4000** | **100%** | |

### 关键指标

- **通过率**（passed/(passed+failed)）：1418/1509 = **94.0%**
- **有效执行**（passed+failed+error）：1521
- **error_type 分布**：assertion=91, timeout=2479, collection=12

---

## 3. 执行历程（多轮，含 bug 修复）

Phase 1 跨 6 轮执行，中途发现并修复了多个 bug：

| 轮次 | batch 范围 | 完成时 test_load 状态 | 说明 |
|------|-----------|---------------------|------|
| 1 | 1-500 | passed=564, pending=2787 | 首轮，发现 5 个启动 bug + GPU 阈值 bug |
| 2 | 501-848 | passed=604, pending=2093 | 续跑，通道中断 1 次 |
| 3 | 849-1101 | passed=1078, pending=1571 | 续跑，failed 重试挤占槽位 |
| 4 | 1102-1296 | passed=1410, pending=1179 | 停止 failed 重试，纯跑 pending |
| 5 | 1297-1437 | passed=1412, pending=17 | **发现 generate_batch 装填率 bug**，修复后装填率 2.4->8.0 |
| 6 | 1381-1384 | passed=1418, **pending=0** | 修边界 bug，清完最后 17->3->0 |

### 速度分析

| 阶段 | batch 范围 | 速度 | 原因 |
|------|-----------|------|------|
| 开头（distributed） | 1-50 | ~5 min/batch | distributed 测试（torchrun 2卡 + 模型加载），多数超时 |
| 中段（normal，bug 前） | 50-1296 | ~0.5 min/batch | normal 测试，但装填率仅 2.4/batch（bug） |
| 修复后（normal） | 1297-1437 | ~0.5 min/batch | 装填率 8.0/batch，效率提升 3.3 倍 |

---

## 4. 失败测试分析

### 4.1 failed（91 个，error_type=assertion）

**按文件分布（top）**：

| 数量 | 文件 |
|------|------|
| 19 | tests/compile/test_fusion_attn.py |
| 8 | tests/basic_correctness/test_basic_correctness.py |
| 3 | tests/compile/distributed/test_async_tp.py |
| 3 | tests/compile/distributed/test_fusions_e2e.py |
| 3 | tests/compile/fullgraph/test_full_graph.py |
| 3 | tests/entrypoints/test_chat_utils.py |

**根因抽样**：91 个 failed 中，多数实际错误信息是：

```
OSError: We couldn't connect to 'https://huggingface.co' to load the files,
and couldn't find them in the cached files. Check your internet connection
```

> ⚠️ 这些被分类为 `assertion`，但实际是 **HuggingFace 网络连接失败**。尽管 `container_env.HF_HUB_OFFLINE=1`，部分测试仍尝试联网下载模型。建议：Phase 2 重新分类为 `network`/`download_error`，并检查模型缓存是否齐全。

### 4.2 error（12 个，error_type=collection）

**按文件分布**：

| 数量 | 文件 |
|------|------|
| 5 | tests/entrypoints/openai/test_translation_validation.py |
| 4 | tests/entrypoints/openai/test_response_api_parsable_context.py |
| 3 | tests/entrypoints/openai/test_response_api_simple.py |

均为 `tests/entrypoints/openai/` 下的 collection 错误（import 阶段失败），可能是依赖缺失或模块变更。

### 4.3 ignored（2479 个，error_type=timeout）

**ignored 原因（两类）**：

| 数量 | 原因 |
|------|------|
| ~1500 | `JUnit XML has no <testcase> (pytest aborted pre-result)` |
| ~980 | `JUnit XML missing (watchdog SIGKILL or fetch empty)` |

> - **SIGKILL**：测试超过 wall_timeout=300s 被 watchdog 杀死（distributed/大模型测试）
> - **no testcase**：pytest 启动后未产出结果就退出（collection 阶段失败、模型下载卡住、GPU OOM）
> - ignored 占比高（62%），主因是 wall_timeout=300s 对部分 distributed/大模型测试不够

---

## 5. 通过测试分析

**passed 按文件分布（top）**：

| 数量 | 文件 |
|------|------|
| 435 | tests/kernels/attention/test_cache.py |
| 44 | tests/compile/distributed/test_fusions_e2e.py |
| 33 | tests/compile/test_fusion_attn.py |
| 23 | tests/compile/test_dynamic_shapes_compilation.py |
| 20 | tests/distributed/test_sequence_parallel.py |

kernels/attention 类测试整体通过率高。

---

## 6. 本次运行修复的 bug（全部生效）

本次 Phase 1 启动前 + 运行中修复了 9 个 bug，全部生效：

| # | bug | 修复 | 验证 |
|---|-----|------|------|
| 1 | `create_batch_id()` 多 `_{index:04d}` 后缀违反 schema | 去后缀 | 1384 batch ID 全合法 ✓ |
| 2 | Windows GBK 编码崩 ✓/✗ 符号 | `PYTHONUTF8=1` | 25 小时无编码崩溃 ✓ |
| 3 | `torchrun ... python3 -m pytest` 把 python3 当脚本 | 改 `-m pytest` | distributed 测试能跑 ✓ |
| 4 | manifest 与 vllm 代码不同步（FP8->NVFP4） | 重新生成+合并 | 无 stale 节点 ✓ |
| 5 | pi auto-checkpoint 回退 git-tracked 编辑 | 禁用扩展 + skip-worktree | 修复持久 ✓ |
| 6 | GPU 空闲判定看利用率不看显存（GPU 0 占 86% 显存但 0% 利用率被误判空闲 -> OOM） | 改显存占用比 < 50% | GPU 0 被正确排除 ✓ |
| 7 | manifest 状态冻结，generate_batch 重复选已跑过的 | 改从 test_load 选 | 重复选中 378->0 ✓ |
| 8 | normal 候选不足时丢弃 distributed，装填率 25% | `len(normal)>=batch_size` 降级 distributed | 装填率 2.4->8.0 ✓ |
| 9 | normal 不足且无 distributed 时抛 ValueError | `or not distributed` 回退 normal | 最后 3 个 pending 跑完 ✓ |

详见 incident 文档：
- [`2026-07-18-phase1-startup-bugs-and-auto-checkpoint-rollback.md`](../incidents/2026-07-18-phase1-startup-bugs-and-auto-checkpoint-rollback.md)（bug 1-6）
- [`2026-07-19-generate-batch-normal-starvation-incident.md`](../incidents/2026-07-19-generate-batch-normal-starvation-incident.md)（bug 7-9）

---

## 7. 运行中的问题与处理

### 7.1 远端 SSH 通道卡死（多次）

- **现象**：`echo` 命令超时（exit=124）或 `Socket is closed`，bastion daemon ping OK 但 SSH 会话不响应
- **根因**：单 SSH channel 被长命令（distributed pytest）占满，并发 `agent.py run` 争抢同一 channel + lock
- **处理**：重启 bastion daemon（`agent.py stop` + `serve` 重建 OTP），清理远端僵尸进程

### 7.2 孤儿 batch 状态

- 本地脚本被中断时，正在执行的 batch 停在 `running` 状态无人清理
- **处理**：从 workflow_state.batches 移除孤儿记录，重置 current_batch，test_load 中该 batch 的测试仍是 pending（会被重新选中）

### 7.3 generate_batch 装填率过低（第 5 轮发现）

- 1210/1308 batch 每个只装 2 个测试（而非 8），装填率 30%
- **根因**：manifest 状态冻结 + normal 候选不足时丢弃 distributed（详见 incident 文档）
- **修复**：改从 test_load 选 + normal 不足降级 distributed，装填率提升至 100%

### 7.4 失败 batch 清理

- 通道中断导致部分 batch 的 batch_results.json 缺失（59 个）
- **处理**：从 workflow_state + checkpoint 移除失败 batch 记录，删除空目录，重跑

---

## 8. 产出文件

| 文件 | 说明 |
|------|------|
| `runs/ut-20260718-164107/phase1_run.log` | 完整运行日志 |
| `runs/ut-20260718-164107/phase1_summary.json` | Phase 1 汇总（1380 success / 4 failed） |
| `runs/ut-20260718-164107/phase1_checkpoint.json` | 1384 batch checkpoint 记录 |
| `runs/ut-20260718-164107/batches/batch_*/` | 1384 个 batch 目录 |
| `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | test_load（4000 全部已处理） |
| `runs/ut-20260718-164107/workflow_state.json` | workflow 状态 |

---

## 9. 建议

### 9.1 Phase 2 处理优先级

1. **failed 重新分类**：91 个 failed 中多数是 HF 网络错误，应重分类为 `network`/`download_error` 并重试（非真正断言失败）
2. **error（12 个）**：openai entrypoints collection 错误，排查依赖
3. **ignored 重跑**：2479 个 ignored，提高 wall_timeout（如 600s）可能让部分 distributed 测试跑完

### 9.2 效率优化

- **提高 wall_timeout**：distributed e2e 测试 300s 不够，建议 600-900s
- **跳过 HF 网络测试**：离线环境下联网测试必失败，可在 filter_rules 中排除
- **generate_batch 已修复**：装填率 100%，无需再优化

### 9.3 已修复的 bug 需提交

本次修复的 3 个文件（`auto_run_batches_two_phase.py`、`execute_batch.py`、`generate_batch.py`）当前带 skip-worktree 标记，需 `--no-skip-worktree` 后 commit。

---

## 10. 关键数据速查

```
Phase 1: 1384 batch, 25h, 99.71% batch 成功率
test_load: 4000 测试 -> 100% 已处理 (pending=0)
  passed=1418  failed=91  error=12  ignored=2479
通过率: 94.0% (1418/1509)
装填率: 8.0/batch (修复后, 修复前 2.4)
```
