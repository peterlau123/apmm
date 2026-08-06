# Phase 2 Timeout 重试：3+1 Bug 修复与全量重试恢复（2026-08-04）

> 场景：run `ut-20260718-164107`（UT Test Workflow v2.2），Phase 1 完成
> （passed=1418 / failed=91 / error=7 / ignored=2484），进入 Phase 2 重试
> 727 个 timeout batch。本文记录 review 发现的 3 个 bug + 过程中发现的
> 第 4 个 bug 的修复，以及全量重试恢复的全过程。

---

## 1. 背景

`phase2_stage1_report.json` 统计：timeout=727、assertion=39、collection=4、filtered=3。
Phase 2 Stage 2 的正式流程是：小规模验证 → 分析已跑 batch → 全量重试 → 刷新 stats + 生成报告。
但 review 发现 3 个 bug 会导致重试结果无法正确回写，先修复再恢复流程。

---

## 2. Bug 修复

### 2.1 Bug 1：旧 batch_results.json 残留 → "假成功"

**症状**：重试失败的 batch 被误判为成功。`execute_batch.py` 子进程实际失败
（daemon 侧 `TimeoutError`），但 `has_result` 读到 **Phase 1 时期残留的旧
`batch_results.json`**，返回假 done，统计被污染。

**根因**：重试前不清理旧结果文件，"失败 = 无文件"的判定失效。

**修复**（`retry_timeout_batches.py` / `phase2_stage2.py`）：执行前
`rp2.unlink(missing_ok=True)` 删除旧结果文件，保证失败=无文件=真实失败。

### 2.2 Bug 2：workflow_state 路径反斜杠 → 路径解析失败

**症状**：`workflow_state.json` 的 `paths.test_load` 是 Windows 风格反斜杠
（形如 `runs\\ut-xxx\\test_load.json`），Linux 下 `Path(test_load_path).exists()`
永远 False → 回写被静默 skip。

**根因**：workflow_state 由 Windows 环境生成，路径分隔符未归一化。

**修复**（`update_test_load_two_phase.py` main + `phase2_stage2.py`）：
抽出模块级 `_resolve_test_load_path(tl_path, wf_path)` 三步归一化：
① 反斜杠→正斜杠 ② 首段 `runs/` 锚定项目根 ③ 否则锚定 `wf_path.parent`。
与参考 commit `de70d48` 保持一致。

### 2.3 Bug 3：重试结果不回写 test_load

**症状**：重试跑完后结果只停在 `batch_results.json`（单批），下游
（test_load / workflow_state.stats）完全看不到。

**根因**：`retry_timeout_batches.py` 只执行 batch，从不调
`update_test_load_two_phase.py` 回写。

**修复**：每批成功后即时调用 `update_test_load_two_phase.py`
（`--batch-id` / `--batch-results` / `--workflow-state`），
并在该脚本 main 里同样修反斜杠路径解析（否则回写被静默 skip）。

### 2.4 Bug 4（过程新发现）：execute_batch container_env 丢失 → 测试联网失败

**症状**：小规模验证时测试在 H20 上**真实执行**了（vLLM 侧日志为证），
但全部联网 huggingface.co 失败（`Couldn't connect to huggingface.co` +
5 次×10s 重试）——HF 离线缓存变量根本没进容器。

**根因**（两个叠加）：
1. `paths.workflow_yaml` 同样是反斜杠路径 → Linux 下读不到 workflow.yaml
2. retry 脚本传 `--timeout` 后 `exec_config` 非 None → execute_batch L845
   **短路跳过 container_env 读取** → `HF_HUB_OFFLINE` / `HF_HOME` /
   `HF_HUB_CACHE` / `TRANSFORMERS_CACHE` / `HF_DATASETS_CACHE` 全丢

**修复**（`execute_batch.py`）：
- container_env 读取独立于 exec_config（exec_config 显式带 container_env 才覆盖）
- workflow_yaml 路径反斜杠归一化 + 锚定
- `workflow_state_path.exists()` 守卫（兼容 unit test 场景）

---

## 3. 修复验证

| 验证点 | 结果 |
|--------|------|
| 单测 | `tests/test_two_phase_fixes.py` 新增 8+4 用例 → 29 passed |
| 全量测试 | **508 passed / 5 skipped，零回归** |
| 小规模重试（--limit 2） | ✅ 2 batch 真实执行 5-6 分钟，test_load 回写成功（mtime 更新） |
| stats 刷新 | ✅ workflow_state.stats 1422/96/2475（反映重跑成果） |

提交：`f372523`（bug 1-3）、`1c1f2a3`（bug 4）。

---

## 4. 方案 C：动态并行度

**背景**：8 并发实测压垮 daemon（任务洪峰：外部并发 × 内部并行 >> daemon
max_concurrent=10），2 并发稳定但慢（727 batch 要 30-60 小时）。

**改动**（`retry_timeout_batches.py`）：
- `--concurrency` 默认 None → 探测 H20 空闲 GPU 数（`compute_parallelism`，
  max_parallel=8），显式传参覆盖
- 探测失败 fallback 4（保守，避免压垮 daemon）
- 修复 PROJECT_ROOT 未加入 sys.path 导致 `tools.remote_executor` 导入失败

提交：`bbc1704`、`b0e8cc7`。

---

## 5. 当前状态（2026-08-04）

全量重试稳定运行中：727 个 timeout batch、外部并发 2、per-test timeout 600s。

```
[1/727] batch_20260718_204040: done rc=0 p=4 f=4 e=0 i=0 331s
```

- test_load：passed 1429 / failed 102 / ignored 2462（持续回写中）
- daemon：单实例、心跳正常、任务持续处理

**待办**（重试跑完后）：
1. 刷新 `workflow_state.stats`（从更新后的 test_load 重新统计）
2. 生成 `phase2_stage2_report.json`（哪些 batch 重试了、成功/失败）
3. 收尾 Phase 2

---

## 6. 相关文件

- `tasks/ut/scripts/retry_timeout_batches.py` — 重试入口（删旧文件 + 回写 + 动态并行度）
- `skills/ut/ut_common/update_test_load_two_phase.py` — test_load 回写（反斜杠修复）
- `skills/ut/ut_common/two-phase-handler/scripts/phase2_stage2.py` — Stage 2（路径修复）
- `skills/ut/unit-test-executor/scripts/execute_batch.py` — container_env 修复
- `tests/test_two_phase_fixes.py` — 新增测试

*更新时间: 2026-08-04*
