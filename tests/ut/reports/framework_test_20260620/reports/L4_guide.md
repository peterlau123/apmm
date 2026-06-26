# UT Framework 测试进度总结 + L4 开展指南

> 基于 spec：`tasks/ut/docs/designs/2026-06-20-ut-framework-test-and-perf-design.md`
> 实现计划：`tasks/ut/docs/plans/2026-06-20-ut-framework-test-and-perf-implementation.md`
>
> 更新日期：2026-06-20

---

## 一、总体进度

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 1** | 测试组织 + perf harness + 指标采集器 | ✅ 完成 |
| **Phase 2** | L1 单测覆盖（含 Kanban 通道补齐） | ✅ 完成 |
| **Phase 3** | L2 mock 管道吞吐（8/16/32） | ✅ 完成 |
| **Phase 4** | L3 真实远程端到端 | ✅ 完成 |
| **Phase 5** | 分析 + 框架 bug 修复 | ✅ 完成 |
| **Phase 6** | L4 真机 Kanban（需用户协同） | ⏳ 待执行 |

**L1→L3 + 修复已全部完成；L4 需用户在场协同，环境脚本已就绪。**

---

## 二、各层测试结果

### L1 单测套件

- 起始：75 passed / 2 skipped
- 当前：**148 passed / 2 skipped**（+73 tests，含 Phase 5 修复测试）
- 新增覆盖：Kanban 通道（orchestrator / board / gateway）
- 产物：`L1_baseline.txt`

| 新增测试文件 | 测试数 | 覆盖点 |
|-------------|--------|--------|
| `test_perf_metrics.py` | 6 | 吞吐计算、stage 累计 |
| `test_kanban_orchestrator_mock.py` | 9 | 多轮 reconcile + select、依赖处理 |
| `test_kanban_gateway.py` | 11 | gateway 心跳检测 |
| `test_kanban_board.py` | 23 | parse_command、refresh_manifest_stats |
| `test_synthetic_manifest.py` | 29 | 合成 manifest schema + 比例 |

### L2 Mock 管道吞吐

| n | passed | failed | error | wall_clock | throughput |
|---|--------|--------|-------|------------|------------|
| 8 | 8 | 0 | 0 | 0.009s | 53,459/min |
| 16 | 14 | 1 | 1 | 0.011s | 90,557/min |
| 32 | 27 | 4 | 1 | 0.01s | 196,781/min |

- 状态机转移验证：**通过**（pending→passed/failed/error，retry 逻辑正确）
- 框架开销 ~6ms（可忽略），近线性扩展
- 产物：`L2_results.json`

### L3 真实远程

| 子集 | 结果 | 远程耗时 | 说明 |
|------|------|---------|------|
| 快测（8） | 8/8 passed | 1.28s pytest + 9.9s SSH | SSH 往返占 78% |
| retry（3） | 2 fail + 1 error | ~600s | 网络超时（模型下载）|

- 快测吞吐：~375 tests/min
- retry 子集失败为可处理类型（download/network），但**初次执行暴露了 4 个框架 bug**，导致修复闭环未触发
- 产物：`L3_fast_results.json`、`L3_retry_results.json`、`L3_execution_report.md`、`L3_rollback.txt`（无 vLLM 改动，无需回滚）

### Phase 5 框架 Bug 修复（TDD）

| Bug | 组件 | 问题 | 修复 |
|-----|------|------|------|
| #2 | `execute_batch.py` | pytest 缩写输出无法匹配 test_node | 前缀匹配 |
| #3 | `run_pipeline_perf.py` | 覆盖了完整 batch_results，manifest 不更新 | 从 path 读完整结果 |
| #1 | `_perf.py` / harness | metrics 读错 key | #3 连带修复 |
| #4 | `analyze_failures.py` | failure-handler 未触发 | #2/#3 修复后自解 |

- 修复后 L1：**148 passed / 2 skipped**（无回归）
- 产物：`analysis_report.md`

---

## 三、吞吐瓶颈结论

| 瓶颈 | 影响 | 优化方向 |
|------|------|---------|
| **SSH 往返**（主） | 快测 78% 时间耗在 2 次 SSH | pytest+grep 合并为 1 次 SSH；daemon 复用连接 |
| **批次串行**（次） | batch 内测试串行执行 | 快测增大 batch_size；慢测减小 |
| JSON I/O | <1% | 可忽略 |
| 状态机开销 | <1% | 可忽略 |

- Mock vs Real 吞吐比 **66,000:1** → mock 模式适合 CI 跑框架逻辑

---

## 四、交付产物清单

```
tasks/ut/framework_test/
├── README.md                    # 测试总入口（导航）
├── results/
│   ├── L1_baseline.txt          # L1 覆盖基线
│   ├── L2_results.json          # L2 mock 吞吐（3 组）
│   ├── L3_fast_results.json     # L3 快测结果
│   ├── L3_retry_results.json    # L3 retry 结果
│   └── L3_rollback.txt          # 回滚状态（无改动）
└── reports/
    ├── analysis_report.md       # 吞吐分析 + bug 修复文档
    ├── L3_execution_report.md   # L3 详细 bug 报告
    └── L4_guide.md              # 本文档（进度总结 + L4 指南）

tests/ut/integration/
├── _perf.py                     # PerfMetrics 采集器
├── _synthetic_manifest.py       # 合成 manifest 生成器
├── run_pipeline_perf.py         # 统一 perf harness（mock/real）
├── run_linear_smoke.py          # 3 例 smoke（薄封装）
├── start_hermes_ut_runtime.py             # L4 启动脚本（gateways+supervisor，daemon 须先起）★
└── fixtures/
    ├── l3_fast_subset.txt       # 8 快测
    └── l3_retry_subset.txt      # 3 retry

skills/ut/hermes-workflow/scripts/
└── start_supervisor.py          # Supervisor 启动脚本 ★

skills/ut/terminal-workflow/scripts/
└── start_gateway.py             # Gateway 启动（既有，共用）

pytest.ini                       # markers: unit/integration/perf/remote
```

---

## 五、L4 真机 Kanban 测试如何开展

### 5.1 测试目标

验证 Kanban 模式下 **executor → fixer 依赖链** 与真机调度：

```
Round 1: executor 并发执行 → 回报 pass/fail/error
   ↓ (executor 完成信号)
Round 2: fixer 处理失败 → 修复 → fixed_pending_verify
   ↓
Round 3: executor 重跑修复后的测试 → pass/fail
```

### 5.2 测试内容清单

| 类别 | 验证点 |
|------|--------|
| **依赖链时序** | fixer 只在 executor 完成后启动；不抢任务 |
| **并发执行** | 3 Gateway 并发作 executor，吞吐提升 |
| **状态转移** | pending→failed→fixed_pending_verify→pass 完整链路 |
| **认领机制** | 多 Gateway 竞争认领，只一个成功 |
| **超时回收** | Gateway 超时未回报 → orchestrator 重分配 |
| **Kanban 专用函数真机验证** | orchestrator_round / check_gateways_alive / parse_command / refresh_manifest_stats |
| **vs Linear 对比** | 并发收益 vs 调度开销 |

### 5.3 测试用例（复用 L3 子集）

| 子集 | 用例数 | 验证目标 |
|------|--------|---------|
| 快测 | 8 | executor 并发吞吐（预期全 pass，无 fixer） |
| retry | 3 | executor → fixer → executor 完整依赖链 |

### 5.4 环境组件（本机 Windows）

| 组件 | 角色 | 启动方式 |
|------|------|---------|
| Bastion daemon | SSH 复用 | `python tools/agent.py serve t_h20`（手动输 OTP） |
| ut-orchestrator Gateway | Stage 5 reconcile + Stage 2 select | 后台 |
| ut-executor Gateway | t_h20 上跑 pytest | 后台 |
| ut-fixer Gateway | 分析失败 + 修复 | 后台 |
| ut-supervisor Agent | 订阅飞书、跑状态机、监控 | 后台 |

### 5.5 配置准备（你需完成）

仅两项需手动准备（其余已在 `.agents/workflow.yaml` 配好：`kanban.enabled: true`、
`kanban.profiles`、`notifications.feishu_chat_id`、board `apmm-ut`）：

| 项 | 操作 |
|------|------|
| `.bastion_creds` | `python tools/agent.py setcreds t_h20`（配静态密码、daemon_port） |
| Hermes profiles | `hermes profile list` 应有 ut-orchestrator/executor/fixer/supervisor |

一条命令校验全部前置项是否就绪（含配置预检 + 运行态）：
```powershell
python tasks/ut/scripts/start_hermes_ut_runtime.py --status
```

### 5.6 开展步骤

**Step 1 — 手动启动 Bastion daemon**（新窗口，OTP 无法脚本化）
```powershell
python tools/agent.py serve t_h20
# 输入静态密码 + OTP，daemon 保持运行
```

**Step 2 — 启动 gateways + supervisor**（非交互；daemon 须已运行）
```powershell
cd D:\workspace\apmm
python tasks/ut/scripts/start_hermes_ut_runtime.py
# 先跑配置预检 → 校验 daemon → 后台起 3 Gateway + Supervisor
```

**Step 3 — 确认环境就绪**
```powershell
python tasks/ut/scripts/start_hermes_ut_runtime.py --status
# 期望 Config: [OK] READY 且全部 [OK] running，Overall: [OK] READY
```

**Step 4 — 飞书触发测试**
在 `apmm-ut` 群发送：
```
跑 ut workflow
```
收到参数确认卡片后回复：
```
改 test_list_path=tests/ut/integration/fixtures/l3_retry_subset.txt
改 batch_size=3
改 kanban.enabled=true
确认
```

**Step 5 — 观察依赖链日志**
```powershell
# Round 1: executor
Get-Content .agents\logs\gateway_ut-executor.log -Wait
# Round 2: fixer（应在 executor 完成后才出现）
Get-Content .agents\logs\gateway_ut-fixer.log -Wait
# Supervisor 调度
Get-Content .agents\logs\supervisor_ut-supervisor.log -Wait
```

**验证依赖链时序**：
1. executor 日志先出现（Round 1）
2. executor 完成 → 看板 executor_done
3. fixer 日志随后出现（Round 2，**不提前**）
4. fixer 完成 → fixed_pending_verify
5. executor 再次出现（Round 3 重跑）

**Step 6 — Kanban vs Linear 对比**（同子集跑 Linear）
飞书回复 `改 kanban.enabled=false` + `确认`，记录吞吐对比。

**Step 7 — 停止环境**
```powershell
python tasks/ut/scripts/start_hermes_ut_runtime.py --stop
```

### 5.7 预期产出

- `L4_kanban_results.json`：多轮调度日志、Gateway 认领/耗时、吞吐
- 更新 `analysis_report.md`：补 L4 vs L3（linear）对比
- 若远程对 vLLM 有改动 → 回滚并记录

### 5.8 风险与注意

| 风险 | 应对 |
|------|------|
| OTP 无法脚本化 | Bastion daemon 必须手动启动 |
| `check_gateways_alive` 用非 `--user` systemctl | 本机 Windows 无 systemd，确认 Hermes 自带的 gateway list 校验生效（DEPLOY-CONFIRM） |
| 真机修复改动 vLLM | 用专用分支/备份，完成后回滚 |
| 远程波动影响计时 | 多跑 1-2 次取稳定值，优先快测 |

---

## 六、下一步

1. **你准备环境文件**（5.5）：`.bastion_creds`、飞书绑定、确认 profiles
2. **约一个协同会话**（30-60min）
3. 我协助逐步启动组件、观察依赖链、记录 L4 结果并补充分析报告
