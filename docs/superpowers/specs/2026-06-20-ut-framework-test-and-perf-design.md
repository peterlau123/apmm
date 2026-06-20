# UT Workflow 框架测试 + 性能度量设计

> 测试对象：**本 repo 的 UT workflow 框架代码**（两条通道：`ut/workflow` 线性 + `hermes_workflow`），
> **不是**远程 vLLM 测试本身。目标是完整覆盖当前功能、度量正确性与执行吞吐，并据结果修复/优化我方框架。

- 日期：2026-06-20
- 状态：Design（待实现计划）
- 相关：Plan 1 (`docs/superpowers/plans/2026-06-19-hermes-workflow-foundation.md`)、Plan 2 (`docs/superpowers/plans/2026-06-20-hermes-workflow-deployment.md`)、Spec v5 (`docs/superpowers/specs/2026-06-18-hermes-workflow-dual-channel-design.md`)

---

## 1. 目标与成功标准

**目标：** 在正式小规模测试前，先把当前框架功能完整覆盖测一遍（绿基线），再分三层度量正确性与吞吐，据结果修复/优化我方代码。

**成功标准：**
- L1 单测套件全绿（当前 69 passed / 2 skipped 不退化），两通道关键函数均有覆盖。
- L2 管道（mock 远程）在 8/16/32 用例下功能正确（manifest 状态机转移符合预期，含失败用例），并产出处理吞吐数据。
- L3 真实远程 8 用例端到端通过，验证 `execute_batch` 远程路径，并产出真实吞吐数据。
- 吞吐指标按统一定义输出（cases/min，分母含 pass+fail+error）+ per-stage 耗时拆解。
- 发现的**我方框架 bug** 被修复；vLLM 用例自身失败仅分类记录。

**非目标（Out of Scope）：**
- 修改 vLLM 源码或让远程 vLLM 用例“变绿”——那是另一个任务，本设计只把它们当作输入/输出信号。
- 真实 Kanban 3-Gateway 在线吞吐（本机无 Hermes Gateway）——用 mock-gateway 模拟覆盖逻辑，真机 Kanban 标注为部署时验证。
- 性能“调优到某个目标值”——本设计只**度量 + 定位瓶颈 + 在范围内修复**，不承诺具体吞吐 KPI。

---

## 2. 三个测试层次

| 层 | 测什么 | 环境 | 度量 |
|----|--------|------|------|
| **L1 单测套件** | 框架函数级正确性（现有 71 单测 + 覆盖缺口） | 本地 pytest | 正确性 + 套件执行吞吐 |
| **L2 管道吞吐（mock 远程）** | 8/16/32 合成用例走 `select_batch → execute_batch(mock run_remote) → analyze_failed_tests_v5 → update_manifest` | 本地 | 框架处理吞吐（含 mock 失败）+ manifest 状态机正确性 |
| **L3 真实远程** | 8 个不需模型下载的轻量真实用例，走 bastion→t_h20→docker→pytest | 远程（bastion 在线） | 端到端真实吞吐 + `execute_batch` 远程路径验证 |

两通道覆盖：
- **ut/workflow（线性）**：hermes_runner 线性路径、`loop_core.run` 回调契约（L1）；L2/L3 即线性管道。
- **hermes_workflow（Kanban）**：`orchestrator_round` 多轮 reconcile+select、`parse_command`、`refresh_manifest_stats`、`otp_resend_delay/otp_should_at_user`、`check_gateways_alive`（L1，gateway/board 层 mock）。真机 Kanban 部署时验证。

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
- **L3（real）**：从 `tasks/ut/test_analysis/manifest.json` 选 **8 个不需模型下载、历史 passed 的轻量用例**（复用已知 6,411 passed 集 + 路径启发式排除 `models/`、需权重的用例），构子集 manifest；预检 `python tools/agent.py -p t_h20 ping` + 分支。

---

## 6. 实施阶段

1. **测试组织**：加 markers + perf harness + 指标采集器（先用单测验证指标计算）。
2. **覆盖基线**：跑 L1 全部；补齐两通道未覆盖函数（含 Kanban mock-gateway 编排多轮测试）。
3. **准备**：造 L2 合成 manifest；选 L3 快测子集 + 预检。
4. **实施**：L1 套件吞吐；L2 跑 8→16→32；L3 跑 8 真实。各产出指标。
5. **分析/修复/优化**：修我方框架 bug；定位吞吐瓶颈（如每用例一次 SSH 往返、串行批次、JSON 反复读写）；在范围内优化并复测。

---

## 7. 修复边界

- **修**：我方框架代码（hermes_runner / generate_batch / execute_batch / analyze_failures / update_manifest / loop_core / bastion_manager / shared/*）中暴露的 bug、契约不一致、性能热点。
- **不修**：vLLM 源码、vLLM 用例自身的 fail/error（仅按 `error_type` 分类记录）。
- 每个修复遵循 TDD：先写/改测试复现，再修，保持 L1 全绿。

---

## 8. 风险

- **L3 真实计时受远程波动影响**（GPU 排队、SSH 抖动）：多跑 1–2 次取稳定值；优先快测避免下载主导。
- **mock 比例不代表生产**：L2 吞吐是“框架上限”参考，非生产预测；文档注明。
- **成本**：全实现是大工程，实现计划应分批（建议 subagent-driven），允许只先做 L1+L2、L3 增量。
