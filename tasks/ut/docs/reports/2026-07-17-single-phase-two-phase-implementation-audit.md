# Single-phase / Two-phase 实际实现逻辑审查报告

**审查日期:** 2026-07-17
**审查范围:** UT Workflow 运行策略(single-phase / two-phase)的实际代码实现、数据流、与真实 run 产物的一致性
**审查方法:** 代码静态阅读 + 实际 run 产物比对 + git 时间线交叉验证
**审查者:** AI Agent (pi, single/two-phase audit)

---

## 0. TL;DR

| 策略 | 实现成熟度 | 核心问题 |
|---|---|---|
| **single-phase** | 纯 prose,无代码骨架 | 正确性全靠 Agent 自觉,无代码强制 |
| **two-phase** | 有 3 个脚本骨架 + 检查点 | refactor 后未验证(F3)、Stage1 回归漏 ignored(F1)、fallback 双计数(F2)、错误信息被吞(F5) |

**修复状态(2026-07-17):** F1 ✅已修+验证 · F2 ✅已修+验证 · F3 ✅已验证 · F5 ✅已修+验证 · F4 ⏸评估后defer(见 §8)

---

## 1. 架构定位:两个独立维度

UT Workflow 有两个正交维度,本次审查聚焦维度 2(策略):

```
维度1 通道(channel):  terminal-workflow  /  hermes-workflow
维度2 策略(strategy): single-phase       /  two-phase
```

`workflow.execution_strategy` 字段决定走哪条策略。通道 × 策略 = 4 种组合(见设计文档 `2026-07-06-two-phase-strategy-design.md`)。

---

## 2. Single-phase 实际实现:无代码,纯 Agent prose 驱动

### 2.1 关键事实

| 项 | 事实 |
|---|---|
| `loop_core.py` | **不存在**。全仓库仅 `tests/ut/unit/test_loop_core_contract.py`,且全部 `@pytest.mark.skip`,注释写明 "loop_core is currently SKILL.md-only" |
| 执行主体 | Agent 读 `skills/ut/workflow-loop-core/SKILL.md` 的伪代码算法,**手动**循环调用 4 个 worker 脚本 |
| 单次循环 | `generate_batch.py`(Stage2) -> `execute_batch.py`(Stage3) -> failure-handler(Stage4) -> `update_test_load.py`(Stage5) -> 检查 `pending==0` |
| 保障机制 | `terminal-workflow/SKILL.md` 的 "Hard Constraints":逐 stage 检查 `workflow_state.json` 状态,未更新则手动补救(`loop_executor.py::remediate_batch_state`) |

### 2.2 结论

single-phase 的正确性**完全依赖 Agent 是否严格按 SKILL.md 走**。没有任何 Python 代码在 `execution_strategy=="single-phase"` 时强制进入该分支,也没有 `loop_core.run()` 函数实现。

---

## 3. Two-phase 实际实现:3 个脚本 + 人工决策点

| 阶段 | 脚本 | 职责 |
|---|---|---|
| Phase 1 | `tasks/ut/scripts/auto_run_batches_two_phase.py` | 脚本批量执行 + 4 强制检查点 + checkpoint resume |
| Phase 2 Stage 1 | `skills/ut/ut_common/two-phase-handler/scripts/phase2_stage1.py` | 按 error_type 统计分析,等待人工决策 |
| Phase 2 Stage 2 | `skills/ut/ut_common/two-phase-handler/scripts/phase2_stage2.py` | 按人工决策重试 batch |
| 共用 | `skills/ut/ut_common/update_test_load_two_phase.py` | batch 完成后 v5 merge test_load + 更新 workflow_state |

数据流(两策略共用):`test_load`=工作数据集(运行期读写),`manifest.json`=主记录(仅 pending==0 后回写),`workflow_state.json`=运行状态。

---

## 4. 关键发现(按严重度排序)

### 🔴 F1 [回归] phase2_stage1.py 漏统计 `ignored` 状态

**位置:** `phase2_stage1.py` `classify()`

```python
def classify(tests, batch_id, stats):
    for t in tests:
        st = t.get("status", "pending")
        if st not in ("failed", "error"): continue   # ← ignored 被跳过
```

**证据(真实 run `runs/ut-20260716-221134/`):** test_load 8 个测试全为 `status=ignored`(timeout, "JUnit XML missing / watchdog SIGKILL")。旧版报告字段 `total_failed_or_ignored_tests` 证明旧版统计 ignored;当前重构版 `classify()` 只统计 `failed`/`error`,同一份 test_load 跑会输出**空 error_statistics**,Phase 2 失效。

### 🟠 F2 [逻辑 bug] phase2_stage1.py fallback 导致双计数

```python
for bid in batch_ids:
    bt = [t for t in tl.get("tests",[]) if t.get("last_batch_id")==bid]
    if not bt: bt = [t for t in tl.get("tests",[]) if t.get("status")!="pending"]  # ← 兜底成全部
    classify(bt, bid, stats)
```

任何空 batch 目录(如 ABORT 残留)会把**所有非 pending 测试**归到自己名下,多 batch 场景下严重双计数。

### 🟠 F3 [未验证] refactor 后脚本未重新跑过

refactor commit `b847dbd` 在 **2026-07-17 13:02**(审查当日),3 次真实 run 都在此之前。实际 run 的 `phase2_stage1_report.json` schema(`run_dir`/`test_load`/`total_tests_in_test_load`/`total_failed_or_ignored_tests` 顶层)与当前脚本输出(`meta.{...}` 包裹 + `summary.total_failed_tests`)**不同**,当前脚本从未用真实数据验证过。

### 🟡 F4 [设计] `execution_strategy` 在代码中只被打印,不被分支

```
create_run_dir.py:80     仅 print
prepare_run_data.py:297  仅 print
```

全仓库无 Python 代码按 `execution_strategy` 分支,完全靠 Agent 读 SKILL.md Step 5 prose。single-phase 无代码强制,two-phase 阶段衔接靠 Agent 自觉。

### 🟡 F5 [实际] Phase 1 错误信息被吞

`runs/ut-20260716-221134/phase1_errors.log` 显示 4 次 ABORT 都卡在检查点1(`generate_batch.py` 没产出 `batch_config.json`)。`create_batch_config()` 用 `capture_output=True`,失败时 stderr 被吞,根因无法追溯。

---

## 5. 修复建议(优先级)

| 优先级 | 项 | 动作 |
|---|---|---|
| P0 | F1 | `classify()` 状态过滤加 `ignored` |
| P0 | F3 | 用真实 test_load 重跑验证 |
| P1 | F2 | 去掉 fallback,空 batch `continue` |
| P1 | F5 | `create_batch_config()` 失败时打印子进程 stdout/stderr |
| P2 | F4 | 评估是否把 strategy 分支落成代码 |

---

## 6. 审查产物引用

| 类型 | 路径 |
|---|---|
| 设计文档 | `tasks/ut/docs/designs/2026-07-06-two-phase-strategy-design.md` |
| Phase 1 脚本 | `tasks/ut/scripts/auto_run_batches_two_phase.py` |
| Phase 2 Stage1 | `skills/ut/ut_common/two-phase-handler/scripts/phase2_stage1.py` |
| Phase 2 Stage2 | `skills/ut/ut_common/two-phase-handler/scripts/phase2_stage2.py` |
| 真实 run | `runs/ut-20260716-221134/` |
| refactor commit | `b847dbd`(2026-07-17 13:02) |
| 回归测试 | `tests/ut/unit/test_phase2_audit_fixes_regression.py` |

---

## 7. 真实 run `ut-20260716-221134` 执行链复盘

1. `execution_strategy: "two-phase"`
2. Phase 1 启动,`generate_batch.py` 连续 4 次未产出 `batch_config.json` -> 检查点1 ABORT 4 次(22:19~22:29)
3. 第 5 次成功产出 `batch_20260716_223109`,8 个测试全 timeout(SIGKILL/JUnit XML missing)-> 状态置 `ignored`
4. Phase 2 Stage 1 生成报告(22:35),统计 8 个 timeout/ignored 测试
5. 人工决策 `user_decision.json` = `skip_all`(22:36)-> Stage 2 未执行

---

## 8. 修复状态 (2026-07-17)

### F1 ✅ 已修复 + 验证

`phase2_stage1.py::classify()` 状态过滤扩展为 `("failed", "error", "ignored")`,附 ponytail 注释说明旧版语义。

**验证(F3):** 用 `runs/ut-20260716-221134/` 真实 test_load 重跑,输出 `timeout (P0): 8 tests, 1 batches`,与旧报告数据完全一致(test_count/batch_count/batch_list/test_list/affected_test_files 全相同)。修复前会报 0。

### F2 ✅ 已修复 + 验证

`phase2_stage1.py::main()` 去掉 fallback,空 batch 直接 `continue`(附 ponytail 注释)。

**验证:** 构造 2 batch(1 空)场景,结果 `test_count=2, batch_count=1, batch_list=['batch_A']`,空 batch 未双计数(修复前 batch_count 会是 2)。

### F3 ✅ 已验证

见 F1 验证。新旧报告 schema 差异(`meta` 包裹 / `total_failed_tests` 命名)是 refactor 本身的设计,数据正确性已恢复。schema 统一可作为后续清理项。

### F5 ✅ 已修复 + 验证

`auto_run_batches_two_phase.py::create_batch_config()` 改为:`returncode!=0 或文件缺失` 时都把 `generate_batch.py` 的 stdout/stderr 打到 stderr。保留原语义(returncode!=0 抛 CalledProcessError 交外层续跑;exit0 文件缺失返回路径交检查点1 ABORT)。

**验证(monkeypatch):** Case1 returncode!=0 打印根因 + 抛 CalledProcessError;Case2 exit0 文件缺失打印警告 + 返回不存在路径。两 case 均通过。

### F4 ⏸ 评估后 defer

当前 prose 驱动的 strategy 分支可工作(真实 run 已端到端跑通 two-phase),两策略共用同一套 worker 脚本。引入编排层(如 `run_workflow.py` 读 `execution_strategy` 分发)属新增抽象,收益边际、复杂度上升。按"无未请求抽象"原则 **defer**:保留为已知设计限制,记入 SKILL.md Step 5 prose 即可;若实践中观察到误分支再 revisit。

### 回归测试

新增 `tests/ut/unit/test_phase2_audit_fixes_regression.py`(5 用例:F1×2 / F2×1 / F5×2),全部通过。未改动既有 `test_phase2_scripts.py`。

### 环境注记

审查中发现工作区对部分文件设了 git `skip-worktree` 位(`phase2_stage1.py`、`auto_run_batches_two_phase.py`),并有周期性 `git reset --hard HEAD && git clean -fd`。skip-worktree 文件的修改对 `git status`/`git diff` 不可见但持久;未跟踪新文件会被 clean 清除。提交时需先 `git update-index --no-skip-worktree` 再 `git add`。

---

*报告完成时间: 2026-07-17*
