# Plan: UT Framework Test and Performance Implementation

> Based on spec: `tasks/ut/docs/designs/2026-06-20-ut-framework-test-and-perf-design.md`

---

## Goal

实现三层测试框架验证（L1 单测 → L2 mock 管道 → L3 真实远程），修复发现的框架 bug，产出吞吐度量数据。L4 真机 Kanban 需用户协同，单独排期。

---

## Context

- 当前状态：71 个单测（69 passed / 2 skipped），`run_linear_smoke.py` 存在但固定 3 例真实远程
- 约束：L3 需 bastion 在线；L4 需用户接入协同；成本控制（避免大量远程调用）
- 已有资产：`tests/skills/ut/`（单测）、`tests/integration/run_linear_smoke.py`（smoke）
- 目标覆盖：两条通道（`ut/workflow` 线性 + `hermes-workflow` Kanban）

---

## Tasks

### Phase 1: Test Organization & Infrastructure — Est: 2h

#### 1.1 Add pytest markers — Est: 15min
- 创建 `pytest.ini` 或 `pyproject.toml [tool.pytest.ini_options]`
- 定义 markers: `unit`, `integration`, `perf`, `remote`
- 默认跳过 `remote` marker（`-m "not remote"`）
- **Verification**: `pytest --markers` 显示新 markers

#### 1.2 Create perf metrics collector module — Est: 45min
- 创建 `tests/integration/_perf.py`
- 实现 `PerfMetrics` 类：
  - `record_stage(stage_name: str, duration_ms: int)`
  - `finalize() -> dict`（含 throughput_per_min 计算）
  - 支持 mock/real mode 标记
- **Verification**: 单测 `tests/skills/ut/test_perf_metrics.py` 验证吞吐计算正确

#### 1.3 Refactor run_linear_smoke.py into harness — Est: 1h
- 提取管道逻辑到 `tests/integration/run_pipeline_perf.py`
- 参数化：`--n <count>`, `--mode <mock|real>`, `--seed-from <manifest>`
- 集成 `PerfMetrics` 采集器
- 保留 `run_linear_smoke.py` 为 3 例 smoke 薄封装
- **Verification**: `python tests/integration/run_pipeline_perf.py --n 3 --mode mock` 成功运行

---

### Phase 2: L1 Unit Test Coverage — Est: 3h

#### 2.1 Run L1 baseline and document gaps — Est: 30min
- 执行 `pytest tests/skills/ut/ -v`
- 记录当前：69 passed / 2 skipped / 0 failed
- 生成覆盖率报告：`pytest --cov=skills/ut tests/skills/ut/`
- **Verification**: 输出 `L1_baseline.txt` 含完整结果

#### 2.2 Add missing unit tests for uncovered functions — Est: 2h
优先级（按 spec 两通道覆盖需求）：
- **线性通道缺口**：
  - `hermes_runner.run()` 回调契约（需 mock loop_core）
  - `loop_core.run()` 状态转移（已有 `test_loop_core_contract.py`，确认覆盖率）
- **Kanban 通道缺口**：
  - `orchestrator_round` 多轮 reconcile + select（需 mock gateway/board）
  - `parse_command` 命令解析
  - `refresh_manifest_stats` 统计刷新
  - `otp_resend_delay` / `otp_should_at_user`（已有 `test_otp_resend.py`，确认覆盖）
  - `check_gateways_alive` 心跳检测（需 mock gateway）
- **Verification**: 新增单测全绿，覆盖率提升 >10%

#### 2.3 Add Kanban mock-gateway orchestrator test — Est: 30min
- 创建 `tests/skills/ut/test_kanban_orchestrator_mock.py`
- Mock gateway/board 响应
- 测试多轮 reconcile + select 逻辑
- **Verification**: 测试通过，覆盖 `orchestrator_round` 核心路径

---

### Phase 3: L2 Mock Pipeline Performance — Est: 2h

#### 3.1 Create synthetic manifest generator — Est: 30min
- 创建 `tests/integration/_synthetic_manifest.py`
- 函数：`generate_synthetic_manifest(n, pass_rate=0.75, fail_rate=0.125, error_rate=0.125)`
- 返回符合 v5 schema 的 manifest dict
- **Verification**: 单测验证生成数据符合 schema

#### 3.2 Create fake run_remote injector — Est: 30min
- 在 `run_pipeline_perf.py` 支持 `--mode mock`
- Fake `run_remote` 按配置比例返回合成 pytest 摘要
- Mock SSH/Docker 调用，零真实远程 I/O
- **Verification**: `--mode mock` 运行不触发任何 SSH

#### 3.3 Run L2 harness (8/16/32 cases) — Est: 1h
- 执行 3 组：`--n 8 --mode mock`, `--n 16 --mode mock`, `--n 32 --mode mock`
- 每组记录：wall_clock_s, throughput_per_min, stage_ms breakdown
- 验证 manifest 状态机转移正确（pending→passed/failed/error，retry 逻辑）
- **Verification**: 输出 `L2_results.json` 含 3 组指标 + 状态转移验证

---

### Phase 4: L3 Real Remote End-to-End — Est: 3h

#### 4.1 Pre-flight check — Est: 15min
- `python tools/agent.py -p t_h20 ping`
- 确认 bastion 在线
- 确认 vLLM 分支可访问
- **Verification**: ping 成功返回

#### 4.2 Select L3 test subsets — Est: 30min
- **快测吞吐子集**（8 例）：历史 passed + 无模型下载的轻量用例
  - 从 `manifest.json` 或历史 run 中选择
  - 创建 `tests/integration/fixtures/l3_fast_subset.txt`
- **修复/重试子集**（2-4 例）：历史 fail/error + 可被 failure-handler 处理
  - 选择 dependency/download 类失败（可修复）
  - 创建 `tests/integration/fixtures/l3_retry_subset.txt`
- **Verification**: 两文件各含目标测试列表

#### 4.3 Run L3 fast subset (throughput) — Est: 1h
- `python tests/integration/run_pipeline_perf.py --n 8 --mode real --seed-from l3_fast_subset.txt`
- 记录真实端到端吞吐
- **Verification**: 输出 `L3_fast_results.json`，对比 L2 指标

#### 4.4 Run L3 retry subset (fix-retry loop) — Est: 1h
- 使用 L3 retry subset
- 触发 failure-handler 修复尝试 + 重试闭环
- 验证状态转移：fail → fixed_pending_verify → 重跑 → pass/fail
- **关键**：记录我方修复逻辑执行路径，vLLM 修复本身不作为交付物
- **Verification**: 输出 `L3_retry_results.json` 含完整状态转移日志

#### 4.5 Rollback vLLM changes if any — Est: 15min
- 如 L3 retry 在远程对 vLLM 施加了修复尝试，执行回滚
- 使用专用分支或 git stash
- **Verification**: `git status` 干净，或分支已还原

---

### Phase 5: Analysis & Framework Fixes — Est: 2h

#### 5.1 Analyze metrics and identify bottlenecks — Est: 1h
- 对比 L1/L2/L3 指标
- 定位热点：SSH 往返次数、串行批次、JSON 反复读写、状态机转移开销
- 输出 `analysis_report.md`：
  - 每层吞吐汇总表
  - Stage-by-stage 耗时拆解
  - 瓶颈识别
- **Verification**: 报告清晰，含可执行优化建议

#### 5.2 Fix discovered framework bugs — Est: 1h (variable)
- TDD：先复现 bug（新增单测或集成测试）
- 修复范围（spec §7）：
  - hermes_runner / generate_batch / execute_batch
  - analyze_failures / update_manifest
  - loop_core / bastion_manager
  - shared/* 辅助模块
- 保持 L1 全绿
- **Verification**: 所有单测通过，bug 复现测试通过

---

### Phase 6: L4 Real Kanban (User Collaboration Required) — Est: TBD

**此阶段需用户在场协同，单独排期**

#### 6.1 Setup Hermes + 3 Gateways — Est: 30min
- 用户启动 Hermes server
- 用户启动 3 Gateway instances
- 确认 board 可访问
- **Verification**: Gateways 心跳正常，board 显示 3 workers

#### 6.2 Run Kanban orchestration test — Est: 1h
- 使用 L3 subset
- 验证：
  - orchestrator 多轮 reconcile + select
  - Gateway 认领与依赖链
  - executor/fixer 并发执行
- 记录调度开销
- **Verification**: 输出 `L4_kanban_results.json`，含调度/认领日志

#### 6.3 Analyze Kanban vs Linear — Est: 30min
- 对比 L3 (linear) vs L4 (Kanban) 吞吐
- 评估 Kanban 调度开销 vs 并发收益
- **Verification**: 更新 `analysis_report.md` 含 L4 对比

---

## Dependencies

- **Phase 2 → Phase 3**: L1 单测基线建立后才能开始 L2
- **Phase 3 → Phase 4**: L2 mock 管道通过后才能开始 L3 真实远程
- **Phase 4 → Phase 5**: L3 数据产出后才能分析
- **Phase 6**: 独立于 Phase 1-5，需用户协同，可提前到 Phase 5 完成后约时

---

## Risks

| Risk | Mitigation |
|------|------------|
| L3 远程波动影响计时 | 多跑 1-2 次取稳定值；优先快测避免下载主导 |
| L2 mock 比例不代表生产 | 文档注明 L2 是"框架上限"参考，非生产预测 |
| L3 retry 修改 vLLM | 使用专用分支，完成后立即回滚；不作为交付物 |
| L4 依赖用户在场 | 明确标记为"需协同"，不阻塞 L1-L3 验收 |
| 发现大量框架 bug | Phase 5 预留 variable 时间，必要时拆分修复任务 |
| 成本过高 | L3 仅 8+2-4 例，L4 复用 L3 subset；避免大量远程调用 |

---

## Deliverables

| Phase | Output |
|-------|--------|
| Phase 1 | `pytest.ini`, `tests/integration/_perf.py`, `run_pipeline_perf.py` |
| Phase 2 | `L1_baseline.txt`, 新增单测文件，覆盖率报告 |
| Phase 3 | `L2_results.json`（3 组指标 + 状态验证） |
| Phase 4 | `L3_fast_results.json`, `L3_retry_results.json`, 回滚确认 |
| Phase 5 | `analysis_report.md`, 框架 bug 修复（含单测） |
| Phase 6 | `L4_kanban_results.json`（需用户协同，单独排期） |

---

## Execution Strategy

采用 **Subagent-Driven Development**：

1. **L1 单测覆盖** → 委托 `general` subagent（Phase 1-2）
2. **L2 Mock 管道** → 委托 `general` subagent（Phase 3）
3. **L3 真实远程** → 委托 `general` subagent（Phase 4）
4. **L4 真机 Kanban** → **需用户协同**，单独约时执行

每阶段完成后验收：
- Phase 1: harness 可运行，perf 采集器单测通过
- Phase 2: L1 全绿，覆盖率提升
- Phase 3: L2 产出指标，状态机正确
- Phase 4: L3 产出指标，修复闭环验证
- Phase 5: 分析报告完成，bug 修复验证

---

## Next Steps

1. 用户确认计划（可微调）
2. 启动 Phase 1 (Test Organization)
3. 按序推进 L1 → L2 → L3
4. L4 另约用户协同会话