# UT Workflow 框架测试 + 性能度量设计

> 测试对象：**本 repo 的 UT workflow 框架代码**（两条通道：`ut/workflow` 线性 + `hermes-workflow`），
> **不是**远程 vLLM 测试本身。目标是完整覆盖当前功能、度量正确性与执行吞吐，并据结果修复/优化我方框架。

- 日期：2026-06-20
- 状态：Design（待实现计划）
- 相关：Plan 1 (`tasks/ut/docs/plans/2026-06-19-hermes-workflow-foundation.md`)、Plan 2 (`tasks/ut/docs/plans/2026-06-20-hermes-workflow-deployment.md`)、Spec v5 (`tasks/ut/docs/designs/2026-06-18-hermes-workflow-dual-channel-design.md`)

---

## 1. 目标与成功标准

**目标：** 在正式小规模测试前，先把当前框架功能完整覆盖测一遍（绿基线），再分三层度量正确性与吞吐，据结果修复/优化我方代码。

**成功标准：**
- L1 单测套件全绿（当前 69 passed / 2 skipped 不退化），两通道关键函数均有覆盖。
- L2 管道（mock 远程）在 8/16/32 用例下功能正确（manifest 状态机转移符合预期，含失败用例），并产出处理吞吐数据。
- L3 真实远程 8 用例端到端通过，验证 `execute_batch` 远程路径，并产出真实吞吐数据。
- 吞吐指标按统一定义输出（cases/min，分母含 pass+fail+error）+ per-stage 耗时拆解。
- 发现的**我方框架 bug** 被修复；vLLM 用例自身失败仅分类记录。

**范围说明：**
- **vLLM 修复过程在范围内**：对真实失败用例，要真正跑 failure-handler 的修复尝试 + 重试闭环
  （fail→修复→`fixed_pending_verify`→重跑→pass/fail），目的是**验证我方重试/修复功能逻辑**。
  vLLM 源码改动本身不作为交付物（不强求 vLLM 全绿），但修复流程必须真实执行，且远程改动需可回滚。
- **真实 Kanban 需用户接入协同**：本机无法独自起 3 Gateway，真机 Kanban 验证安排为**与用户协同的实时会话**
  （用户参与起 Hermes/Gateway），不是推迟、也不是只用 mock。mock-gateway 仅用于本地逻辑覆盖（L1）。见 L4。

**非目标（Out of Scope）：**
- 性能“调优到某个目标 KPI 值”——本设计只**度量 + 定位瓶颈 + 在范围内修复/优化**，不承诺具体吞吐数值。

---

## 2. 三个测试层次

| 层 | 测什么 | 环境 | 度量 |
|----|--------|------|------|
| **L1 单测套件** | 框架函数级正确性（现有 71 单测 + 覆盖缺口） | 本地 pytest | 正确性 + 套件执行吞吐 |
| **L2 管道吞吐（mock 远程）** | 8/16/32 合成用例走 `select_batch → execute_batch(mock run_remote) → analyze_failed_tests_v5 → update_manifest` | 本地 | 框架处理吞吐（含 mock 失败）+ manifest 状态机正确性 |
| **L3 真实远程(线性)** | 真实用例（含**可修复失败用例**）走 bastion→t_h20→docker→pytest；触发 failure-handler 修复 + 重试闭环 | 远程（bastion 在线） | 端到端真实吞吐 + `execute_batch` 远程路径 + **重试/修复闭环**验证 |
| **L4 真实 Kanban** | 3 Gateway + orchestrator/executor/fixer 真机编排 | 远程 + Hermes（**需用户接入协同**） | Kanban 调度/认领/依赖链 + 端到端 |

两通道覆盖：
- **ut/workflow（线性）**：hermes_runner 线性路径、`loop_core.run` 回调契约（L1）；L2/L3 即线性管道。
- **hermes-workflow（Kanban）**：`orchestrator_round` 多轮 reconcile+select、`parse_command`、`refresh_manifest_stats`、`otp_resend_delay/otp_should_at_user`、`check_gateways_alive`（L1，gateway/board 层 mock 做逻辑覆盖）。真机 Kanban 验证见 **L4（需用户接入协同）**。

---

## 3. 架构

### 3.1 测试组织（轻量分层，不大动目录）

- 新增 `pytest.ini`（或 `pyproject.toml [tool.pytest.ini_options]`），定义 markers：
  - `unit`：纯本地、无 I/O 的快测（现有 `tests/skills/ut/*`）。
  - `integration`：跨多个 skill 的本地集成（mock 远程，L2）。
  - `perf`：吞吐度量（L2/L3 harness 入口，默认不随普通 `pytest` 运行）。
  - `remote`：需要 bastion 的真实远程（L3，默认 `-m "not remote"` 跳过）。
- 目录保持现状：`tests/skills/ut/`（unit）、`tests/integration/`（harness）。`tasks/ut/workflow_tests/` 维持不动（任务级 fixture）。

### 3.2 统一 perf harness

把现有 `tests/integration/run_linear_smoke.py`（固定 3 例、真实远程）泛化为
`tests/integration/run_pipeline_perf.py`：

```
run_pipeline_perf.py --n <8|16|32> --mode <mock|real> [--seed-from <manifest>]
```

- `--mode mock`：注入一个 fake `run_remote`，按可配置的 pass/fail/error 比例返回合成 pytest 摘要（L2）。
- `--mode real`：走真实 `run_remote`（bastion），用例取自“快测”子集（L3）。
- 两模式共用同一管道驱动与同一**计时/指标采集器**，保证 L2/L3 指标口径一致。
- 输出：JSON + 控制台表格（见 §4 指标）。

`run_linear_smoke.py` 保留为 3 例 smoke（CI/手验），或改为调用 perf harness 的薄封装（实现计划再定，避免重复管道代码）。

### 3.3 指标采集器（共用单元）

一个独立小模块（如 `tests/integration/_perf.py`）：
- 记录 wall-clock（总）与每个 stage 的累计耗时（select / execute / analyze / update）。
- 统计 pass/fail/error/总数。
- 计算吞吐：`throughput = total_cases / wall_clock`（cases/sec 与 cases/min），分母含失败。
- 输出结构化 dict，便于断言（perf 回归）与人读。

职责单一、可独立测试（给它假计时与假计数 → 验证吞吐计算）。

---

## 4. 吞吐指标（统一定义）

| 字段 | 定义 |
|------|------|
| `total` | 本次处理用例总数（pass+fail+error） |
| `passed/failed/error` | 各状态计数 |
| `wall_clock_s` | 端到端墙钟秒 |
| `throughput_per_min` | `total / wall_clock_s * 60`（**含失败用例**） |
| `stage_ms` | `{select, execute, analyze, update}` 各阶段累计毫秒 |
| `mode` | `mock` / `real` |
| `n` | 输入用例数 |

- L1 套件吞吐：用 `pytest --durations=0` + 自定义收尾钩子（或简单包一层计时跑 `pytest -q`），报告 `tests/sec`。
- L2/L3：harness 直接产出上表。

---

## 5. 测试数据准备

- **L2（mock）**：合成 N 条 manifest 用例（`test_id`/`test_node`/`status=pending`/`retry_count`/`max_retry`），fake `run_remote` 按比例（默认 6 pass / 1 fail / 1 error，可参数化）回报，覆盖状态机各分支（pass、fail、retriable_error、达 max_retry）。
- **L3（real）**：两部分子集 ——
  - **快测吞吐子集**：8 个不需模型下载、历史 passed 的轻量用例（吞吐口径干净，不被下载/GPU 排队主导）。
  - **修复/重试子集**：2–4 个历史 fail/error 且**可被 failure-handler 处理**的用例（如 dependency/download 类），用于触发并验证“修复尝试→`fixed_pending_verify`→重跑”闭环。
  预检 `python tools/agent.py -p t_h20 ping` + 分支。修复过程会在远程对 vLLM 施加修复尝试，**先备份/用专用分支，确保可回滚**。
- **L4（real Kanban）**：复用 L3 子集，但经 Hermes 3 Gateway 编排；**与用户协同的实时会话**中进行（用户参与起 Hermes/Gateway/board）。

---

## 6. 实施阶段

1. **测试组织**：加 markers + perf harness + 指标采集器（先用单测验证指标计算）。
2. **覆盖基线**：跑 L1 全部；补齐两通道未覆盖函数（含 Kanban mock-gateway 编排多轮测试）。
3. **准备**：造 L2 合成 manifest；选 L3 快测子集 + 预检。
4. **实施**：L1 套件吞吐；L2 跑 8→16→32；L3 跑快测吞吐子集 + 修复/重试子集（真实执行修复闭环并验证）；**L4 真机 Kanban 另约用户协同会话执行**。各产出指标。
5. **分析/修复/优化**：修我方框架 bug；验证重试/修复闭环正确；定位吞吐瓶颈（如每用例一次 SSH 往返、串行批次、JSON 反复读写）；在范围内优化并复测。

---

## 7. 修复边界

- **修我方框架代码**：hermes_runner / generate_batch / execute_batch / analyze_failures / update_manifest / loop_core / bastion_manager / shared/* 的 bug、契约不一致、性能热点。TDD：先复现再修，保持 L1 全绿。
- **vLLM 修复过程要真实执行**（用于验证我方重试/修复功能）：对真实失败用例，让 failure-handler 走完“修复尝试 → `fixed_pending_verify` → 重跑”闭环；重点是验证**循环逻辑正确**，而非让 vLLM 全绿。远程对 vLLM 的改动需可回滚（备份/专用分支），不作为本任务交付物。

---

## 8. 风险

- **L3 真实计时受远程波动影响**（GPU 排队、SSH 抖动）：多跑 1–2 次取稳定值；优先快测避免下载主导。
- **mock 比例不代表生产**：L2 吞吐是“框架上限”参考，非生产预测；文档注明。
- **真机修复会改动远程 vLLM**：先备份 / 用专用分支，确保可回滚；修复闭环验证后视情况还原。
- **L4 真机 Kanban 依赖用户在场**：需用户协同起 Hermes/Gateway，单独约时进行，不阻塞 L1–L3。
- **成本**：全实现是大工程，实现计划应分批（建议 subagent-driven），按 L1→L2→L3→L4 推进，每层可独立验收。
