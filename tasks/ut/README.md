# UT Workflow — vLLM 单元测试验证

> vLLM 在 MACA H20 硬件上的单元测试执行系统。本 README 只做**任务导向的入口**，详细规范请到下方链接。

---

## 我想干嘛？

### 🅰️ 我要跑这个仓库的测试（最常用）

| 跑什么 | 飞书 apmm-ut 群里说 | 模式 | 用例数 | 耗时 |
|---|---|---|---|---|
| L1 烟雾 | `跑 L1` | linear | 1 | < 1 min |
| L2 mini | `跑 L2` | linear | ~10 | ~3 min |
| L3 fast | `跑 L3` | linear | ~50 | ~15 min |
| L4 retry | `跑 L4` | **kanban** | 3 (retry subset) | ~60 min |
| 正式生产 | `跑 ut workflow 的正式生产` | kanban | 全量 | hours – days |

**前置一次性启动**（gateway + supervisor，幂等，已起则秒退）：
```bash
python tasks/ut/scripts/start_hermes_ut_runtime.py
```
- daemon **不需要预先 serve**，supervisor 会通过飞书 OTP 卡自动索取并自起。
- 状态查询：`... --status`。停止：`... --stop`。

完成后在飞书发触发词即可，supervisor 会发参数确认卡，回 `确认` 启动。

> 不在飞书群里？先拉到 apmm-ut 群里。配置 webhook 见 [skills/ut/terminal-workflow/references/feishu-integration.md](../../skills/ut/terminal-workflow/references/feishu-integration.md)。

---

### ????

??????? UT / ????? / start UT / ??????????????????

```
????? UT ??
  ?
  ?? ???????(OTP / ???? / ????)
  ?   ?? ? ???????????????????????????????> hermes-workflow
  ?   ?? ? ??
  ?          ?
  ?? ?? Kanban ? Agent ???
  ?   ?? ? ???????????????????????????????> hermes-workflow (kanban.enabled=true)
  ?   ?? ? ??
  ?          ?
  ?????????????> terminal-workflow (??????????)
```

| ?? | terminal-workflow | hermes-workflow |
|------|-------------------|-----------------|
| ???? | ??? Agent | ??? Agent ? Kanban ? Agent |
| ???? | ??? | ???OTP??????????? |
| Kanban | ??? | `kanban.enabled=true` ??? |
| ???? | ??????CI ?? | ??????????????? |
| ???? | ?? SKILL.md ????? | ???????????????? |

**????**?Agent ?? UT ?????
1. ???????????????
2. ??? hermes??????? Kanban
3. ??????? SKILL.md????????test_list_path / batch_size / resume_from ??

---



### 🅱️ 我要在终端线性跑（调试 / 人工监督，**ut/terminal-workflow 通道**）

适合开发态、调试 stage 行为、单次跑验证。**禁止开 kanban**（运行时强制校验）。

1. 编辑 `.agents/workflow.yaml`，确保 `kanban.enabled: false`，填好 `test_list_path` / `remote_server`。
2. 在 Claude Code / OpenCode 会话中加载 skill：
   ```
   加载 ut/terminal-workflow skill
   ```
3. Skill 自动初始化 `workflow_state.json` 并循环 Stage 2-5 直至完成。
4. 单独跑一个 test：
   ```bash
   python tools/agent.py -p t_h20 run --timeout 300 \
     "sudo docker exec v0.13.0_torch2.5.1_compile bash -c \
      'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv <test_node>'"
   ```

详见 [skills/ut/terminal-workflow/SKILL.md](../../skills/ut/terminal-workflow/SKILL.md)。

---

### 🅲️ 我要在 Hermes 后台长跑（生产 / L4，**ut/hermes-workflow 通道**）

适合无人值守的长时间运行、L4 集成、生产全量。Kanban 可开可关。

1. 启动同 🅰️。
2. 通过飞书发触发词。
3. supervisor 全权托管：Bastion 心跳、OTP 自动恢复、状态机（running/paused/waiting_otp/completed/stopped/failed）、参数热改。

详见 [skills/ut/hermes-workflow/SKILL.md](../../skills/ut/hermes-workflow/SKILL.md)。

---

### 🅳️ 我对其它方面感兴趣

| 关心什么 | 看这里 |
|---|---|
| **两通道整体对比 + 触发图** | [docs/guides/ut-channels-overview.md](docs/guides/ut-channels-overview.md) |
| 测试目标 / 完成标准 | [GOAL.md](GOAL.md) |
| 实时进度（数字以此为准） | [PROGRESS.md](PROGRESS.md) |
| 每日工作日志 | [WORKLOG.md](WORKLOG.md) · [todo.md](todo.md) |
| 远程环境 / SSH / 容器 / 文件布局 | [docs/guides/testing.md](docs/guides/testing.md) |
| 测试过滤规则（哪些被排除/为什么） | [skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml) |
| Bastion OTP / daemon 设计 | [docs/discussions/2026-06-18-hermes-runner-bastion-otp-design.md](docs/discussions/2026-06-18-hermes-runner-bastion-otp-design.md) |
| Hermes Runner 操作 | [docs/guides/hermes-runner.md](docs/guides/hermes-runner.md) |
| Kanban 配置 | [docs/kanban/README.md](docs/kanban/README.md) |
| Hermes profile 同步 | `python tasks/ut/scripts/deploy_tier.py --tier L4` · [tests/ut/integration/fixtures/profiles/README.md](../../tests/ut/integration/fixtures/profiles/README.md) |
| 故障复盘 / 历史 incident | [docs/incidents/](docs/incidents/) |
| 周报 / 兼容性分析 | [docs/reports/](docs/reports/) |
| 完整流程规范 v2 | [docs/单元测试流程规范_v2.md](docs/单元测试流程规范_v2.md) |
| 完整文档中心 | [docs/README.md](docs/README.md) |

---

## 双通道速查

```
ut/terminal-workflow            (线性通道，开发态)
  └─ 终端会话加载 SKILL → 进程内循环 Stage 2-5
  └─ kanban 强制 OFF

ut/hermes-workflow     (生产通道，长期后台)
  └─ ut-supervisor 飞书订阅 → 触发后 ensure_bastion → loop_core
  └─ kanban 可选；开 kanban 时由 3 个 Gateway (orchestrator/executor/fixer) 协作
  └─ 共用同一份 workflow-loop-core，5 阶段流水线一致
```

5 阶段流水线（两通道共用）：
```
Stage 1 collect → Stage 2 select_batch → Stage 3 execute(远程pytest)
                                       → Stage 4 handle_failures → Stage 5 update_status
                            循环 Stage 2-5 直到 pending == 0
```

---

## 运行策略

UT Workflow支持两种运行策略：

### Single-phase策略（默认）

- **核心思想**: Agent介入每个stage，逐batch处理
- **执行速度**: 较慢（逐batch，agent等待）
- **GPU利用率**: 中等（agent上下文占用）
- **错误处理**: 实时处理（Stage 4立即处理）
- **适用规模**: 小-中规模（1-200 batch）
- **适用场景**: 调试、实时处理

### Two-phase策略

- **核心思想**: Phase 1脚本批量执行 + Phase 2 agent智能处理
- **执行速度**: 快（Phase 1批量执行）
- **GPU利用率**: 高（无agent开销）
- **错误处理**: 延迟处理（Phase 2统计分析）
- **适用规模**: 大规模（500+ batch）
- **适用场景**: 快速验证、生产运行

### 适用场景矩阵

| 场景 | 推荐通道 | 推荐策略 | batch规模 | 原因 |
|------|---------|---------|-----------|------|
| L1烟雾测试 | terminal-workflow | single-phase | 1 batch | 实时调试 |
| L2-L3测试 | terminal-workflow | single-phase | 10-50 batch | 小规模实时处理 |
| 开发态快速验证 | terminal-workflow | two-phase | 100-500 batch | 快速跑完看整体状态 |
| 生产全量测试 | hermes-workflow | two-phase | 500+ batch | Phase 1快速 + Phase 2智能补充 |

---

## Two-phase策略配置参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| execution_strategy | string | 运行策略选择 | "single-phase" |
| batch_group_size | int | Phase 1执行的batch总数 | null（需用户设置） |
| phase1.auto_create_batches | bool | 自动创建batch配置 | true |
| phase1.auto_execute | bool | 自动执行batch | true |
| phase1.checkpoint_interval | int | checkpoint写入间隔 | 10 |
| phase1.enable_force_checkpoints | bool | 启用强制检查点 | true |

---

## Two-phase策略使用指南

### Phase 1执行

```bash
python tasks/ut/scripts/auto_run_batches_two_phase.py \
    --workflow-yaml tasks/ut/deployment/production/config/workflow.yaml \
    --run-dir runs/ut-20260706-123456 \
    --batch-group-size 100
```

### Phase 2处理

Phase 1完成后，调用`two-phase-handler` skill处理失败batch：

```
加载 ut/two-phase-handler skill
```

设计文档见 [docs/designs/2026-07-06-two-phase-strategy-design.md](docs/designs/2026-07-06-two-phase-strategy-design.md)。

---

## 关键数据文件

| 文件 | 位置 | 更新时机 |
|---|---|---|
| `manifest.json` | `test_analysis/manifest.json` | Stage 5 每次循环 |
| `workflow.yaml` | `.agents/workflow.yaml`（生产）/ `tests/ut/integration/fixtures/workflow.l*.yaml`（L1-L4 frozen） | 手动 |
| `workflow_state.json` | `runs/<run_id>/workflow_state.json` | 每次循环 |

Manifest schema 定义见 [skills/ut/shared/manifest_schema.json](../../skills/ut/shared/manifest_schema.json)。

---

## Resume工具集（新增）

> 三重保障：代码强制更新 + 强制输出检查 + SKILL硬性约束

| 工具 | 用途 | 使用场景 |
|---|---|---|
| `workflow_state_manager.py` | 状态管理核心 | 所有Worker脚本必须调用 |
| `resume.py` | 状态分析工具（只读） | 中断恢复、状态诊断 |
| `loop_executor.py` | 自检补救执行器 | 执行batch + 自动验证状态 |

详细使用方法见 [docs/guides/resume-tools-guide.md](docs/guides/resume-tools-guide.md)。

设计文档见 [docs/designs/2026-07-03-resume-mechanism-design.md](docs/designs/2026-07-03-resume-mechanism-design.md)。

---

## 问题分类体系（人读归因）

`C-代码Bug` · `E-环境问题` · `D-依赖缺失` · `P-平台兼容` · `M-模型缺失` · `S-跳过问题`

机器可读的 `error_type` 枚举见 [manifest_schema.json](../../skills/ut/shared/manifest_schema.json)（`dependency`/`network`/`download_error`/`oom`/`timeout`/...）。

---

*Last updated: 2026-07-07*
