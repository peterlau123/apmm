# Hermes Runner + Bastion OTP 托管设计

**Date**: 2026-06-18
**Status**: Design proposal
**Scope**: UT Workflow 运行主体、Bastion daemon 托管、飞书 OTP 交互

---

## 1. 背景

当前 UT Workflow 用于执行 vLLM 单元测试验证，核心流程是 Stage 2-5 循环：

1. `select_batch`：从 manifest 选择下一批测试。
2. `execute`：通过 bastion + Docker 远程执行 pytest。
3. `handle_failures`：分析并处理失败测试。
4. `update_status`：更新 manifest 和 workflow 状态。

当前 bastion 连接依赖人工在单独终端运行：

```bash
python tools/agent.py serve t_h20
```

该命令需要输入 OTP 二次验证码，并保持窗口不关闭。这个模式不适合长时间无人值守的 UT Workflow，因为 daemon 断联、OTP 过期、当前 Agent 会话结束都会导致 workflow 暂停或失败。

---

## 2. 核心结论

**Hermes 更适合作为 UT Workflow 的长期运行主体。**

OpenCode / Claude Code 更适合作为设计、维护、调试和人工监督入口，不适合作为需要持续在线的后台 runner。

推荐第一阶段采用：

```text
Hermes 非 Kanban Runner
+ Bastion Manager
+ 飞书 OTP 收信
+ 单 active batch 顺序执行
```

Kanban 是可选增强层，不是 Hermes 托管 UT Workflow 的必要条件。第一阶段不追求多 batch 并行，也不要求启用 Kanban。

---

## 3. Hermes、OpenCode、Claude Code 的职责差异

| 维度 | Hermes 运行 | OpenCode 运行 | Claude Code 运行 |
|---|---|---|---|
| 长期后台运行 | 最适合 | 不理想 | 不理想 |
| 飞书收信 | 已确认可支持 | 需要额外实现 | 需要额外实现 |
| 飞书通知 | 适合 | 可做 | 可做 |
| OTP 获取 | 可直接接收飞书回复 | 通常要用户回到聊天窗口 | 通常要用户回到聊天窗口 |
| Bastion daemon 托管 | 适合做成 Runner 能力 | 容易依赖当前会话 | 容易依赖当前会话 |
| 断线恢复 | 适合自动化 | 会话型，不稳定 | 会话型，不稳定 |
| Workflow 状态机 | 适合 | 可以做但不自然 | 可以做但不自然 |
| 代码修改/调试 | 不是主职责 | 很适合 | 很适合 |
| 架构讨论/设计 | 不是主职责 | 很适合 | 很适合 |
| 是否适合作为最终 Runner | 是 | 否，适合启动/维护 | 否，适合启动/维护 |

结论：

```text
Hermes = 后台运行器 / 人机交互网关 / 状态机
OpenCode / Claude Code = 工程控制台 / 设计维护入口
```

---

## 4. 目标架构

```text
Hermes Gateway / Runner
  ├─ 接收“启动 UT workflow”指令
  ├─ 读取 .agents/workflow.yaml
  ├─ 初始化或恢复 workflow_state.json
  ├─ Bastion Manager
  │   ├─ ensure_connected(profile=t_h20)
  │   ├─ 15s 心跳检查
  │   ├─ 断联立即飞书富文本通知
  │   ├─ 接收用户在飞书回复的 OTP
  │   └─ 使用 OTP 重启 tools/agent.py serve
  ├─ 顺序执行 Stage 2-5
  ├─ 写入 manifest.json / workflow_state.json / batch files
  └─ 发送 progress / paused / complete 飞书通知
```

UT Workflow 的业务逻辑不需要重写，仍然保留现有 Stage 2-5 和 manifest/batch 数据流。Hermes 只承担运行壳、长生命周期托管和人机交互。

---

## 5. Kanban 取舍

### 5.1 不启用 Kanban 的 Hermes Runner

适合作为第一阶段：

```text
Hermes Runner
  ├─ 单 active batch 顺序执行
  ├─ 复用 workflow_state.json
  ├─ 复用 manifest.json
  ├─ 复用现有 Stage 2-5
  ├─ 接入 Bastion Manager
  └─ 接入飞书 OTP 收信
```

优点：

- 迁移成本低。
- 不改变现有线性 workflow。
- 不引入 board/task/lane 状态同步。
- 更容易先跑稳 bastion 托管和 OTP 恢复链路。

缺点：

- 没有 Kanban board 的可视化状态。
- `waiting_for_otp`、`paused`、`failed` 等状态主要依赖 `workflow_state.json` 和飞书通知表达。

### 5.2 启用 Kanban 的 Hermes Runner

适合作为第二阶段增强：

```text
Kanban Board
  ├─ running
  ├─ waiting_for_otp
  ├─ paused
  ├─ failed
  └─ completed
```

优势是状态可视化和任务管理更好，但不是为了多 batch 并行。当前目标明确保持单 active batch 顺序执行。

结论：

> Hermes 托管 UT Workflow 不依赖 Kanban。Kanban 是状态可视化增强层，不是第一阶段必要条件。

---

## 6. Bastion Manager 设计

建议新增：

```text
skills/ut/terminal-workflow/scripts/bastion_manager.py
```

职责：

- `ensure_connected(profile)`：确保 daemon 已连接。
- 每 15s 执行本地 daemon 心跳：

  ```bash
  python tools/agent.py -p t_h20 ping
  ```

- daemon 断联后立即通知 Hermes/飞书。
- 请求 OTP。
- 收到 OTP 后启动或重启 daemon：

  ```bash
  python tools/agent.py serve t_h20 --otp <OTP>
  ```

- 验证 daemon 恢复后继续 workflow。

心跳分两层：

```text
Layer 1: 本地 daemon 心跳
  Hermes / bastion_manager 每 15s 调用 agent.py ping。

Layer 2: SSH Transport keepalive
  tools/agent.py 内部调用 transport.set_keepalive(15)。
```

不要每 15s 往主 shell channel 发送 `echo __KEEPALIVE__`，否则可能污染 pytest 输出或与长时间运行的远程命令产生锁竞争。

---

## 7. tools/agent.py 设计边界

`tools/agent.py` 仍然只负责 SSH daemon，不承担飞书逻辑。

现有能力已经支持非交互 OTP：

```bash
python tools/agent.py serve t_h20 --otp <CODE>
python tools/agent.py -p t_h20 ping
```

建议只补充 SSH keepalive：

```python
transport.set_keepalive(15)
```

飞书 OTP、断联通知、workflow 暂停/恢复应由 Hermes Runner / Bastion Manager 负责。

---

## 8. 飞书 OTP 会话协议

因为 Hermes 可以接收飞书消息，应定义明确协议，避免误收、串单或泄露 OTP。

每次请求 OTP 时生成：

```json
{
  "request_id": "otp-20260618-xxxx",
  "profile": "t_h20",
  "stage": "execute",
  "batch_id": "batch_123",
  "expires_at": "5min"
}
```

飞书富文本提示用户：

```text
🔴 UT Workflow 需要 Bastion OTP

Profile: t_h20
当前阶段: execute
当前批次: batch_123
请求ID: otp-20260618-xxxx

请回复：
OTP otp-20260618-xxxx 123456
```

接收规则：

- 只接受匹配 `request_id` 的 6 位 OTP。
- OTP 不写入日志。
- OTP 使用后立即清除。
- OTP 请求超时后作废，建议默认 300s。
- 每个 profile 同一时间只允许一个 active OTP request。
- 不接受无 request_id 的裸 OTP，避免误触发。

---

## 9. workflow.yaml 建议新增配置

建议在 `.agents/workflow.yaml` 中新增：

```yaml
bastion:
  managed_by: hermes
  profile: "t_h20"
  heartbeat_interval: 15
  otp_timeout: 300
  notify_on_disconnect: true
  auto_restart: true
```

Runner 从配置读取 profile、心跳间隔、OTP 超时和自动重启策略，避免硬编码。

---

## 10. workflow_state.json 建议新增状态

为了支持 Hermes Runner 重启恢复，应把 bastion 状态写入 `workflow_state.json`：

```json
{
  "bastion": {
    "status": "waiting_for_otp",
    "profile": "t_h20",
    "otp_request_id": "otp-20260618-xxxx",
    "last_heartbeat_at": "2026-06-18T10:00:00+08:00",
    "last_disconnect_reason": "daemon_ping_failed"
  }
}
```

建议状态枚举：

| 状态 | 含义 |
|---|---|
| `connected` | daemon 可用 |
| `disconnected` | daemon 不可用 |
| `waiting_for_otp` | 已通知用户，等待飞书 OTP |
| `reconnecting` | 已收到 OTP，正在重启 daemon |
| `failed` | 重连失败，需要人工处理 |

---

## 11. 当前仓库需要补齐的内容

### 11.1 新增 Hermes 非 Kanban Runner

建议新增：

```text
skills/ut/terminal-workflow/scripts/hermes_runner.py
```

职责：

- 读取 `.agents/workflow.yaml`。
- 初始化或恢复 workflow。
- 顺序执行 Stage 2-5。
- 每轮前确保 bastion 连接可用。
- 状态写入 `workflow_state.json`。
- 发送飞书进度、暂停、完成通知。

### 11.2 新增 Bastion Manager

建议新增：

```text
skills/ut/terminal-workflow/scripts/bastion_manager.py
```

职责见第 6 节。

### 11.3 增强 tools/agent.py

建议补充：

```python
transport.set_keepalive(15)
```

不建议把飞书逻辑放进 `tools/agent.py`。

### 11.4 更新文档和 Skill

实现后更新：

```text
skills/ut/terminal-workflow/SKILL.md
  增加 Hermes 非 Kanban 模式说明。

tasks/ut/docs/guides/hermes-runner.md
  增加启动、恢复、OTP、断联排错指南。

tasks/ut/README.md
  只增加导航入口，不堆详细步骤。
```

---

## 12. 推荐落地顺序

1. **实现 Hermes 非 Kanban Runner**：复用现有线性 Stage 2-5。
2. **接入 Bastion Manager**：启动前 `ensure_connected`，运行中 15s 心跳。
3. **接入 Hermes 飞书收信 OTP**：完成断联 → 请求 OTP → 收到 OTP → 重启 daemon → 恢复 workflow。
4. **再考虑 Kanban 可视化**：线性 Runner 稳定后，再把状态映射到 board。

---

## 13. 非目标

第一阶段不做：

- 多 batch 并行执行。
- 多 executor 同时抢占 GPU。
- 每个 worker 独立启动 bastion daemon。
- 在 `tools/agent.py` 内实现飞书消息收发。
- 强制启用 Kanban。

---

## 14. 最终总结

Hermes 应作为 UT Workflow 的长期运行器，负责后台托管、飞书 OTP、人机交互、bastion 心跳和断联恢复。

OpenCode / Claude Code 应作为工程控制台，用于设计、修改、调试和人工监督。

第一阶段推荐：

```text
Hermes 非 Kanban Runner
+ Bastion Manager
+ 飞书 OTP 收信
+ 单 active batch 顺序执行
```

该方案最小化改动，同时解决当前最关键的问题：UT Workflow 不再依赖人工单独打开 bastion 终端，也不依赖当前 Agent 会话长期在线。
