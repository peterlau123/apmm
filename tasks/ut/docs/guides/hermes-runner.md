# Hermes Runner 操作指南

> UT Workflow 长期运行主体 — 双模式（线性 / Kanban），启动、恢复、OTP 交互、排错

---

## 1. 概述

Hermes Runner (`hermes_runner.py`) 是 UT Workflow 的后台运行器，根据 `workflow.yaml` 中 `kanban.enabled` 自动选择执行模式：

| 模式 | kanban.enabled | 执行方式 |
|------|:---:|------|
| **线性模式** | `false` | 进程内循环 Stage 2-5 |
| **Kanban 模式** | `true` | 启动 Gateway + 3 Worker，监控 board |

两种模式共享：
- Bastian Manager（心跳、断联检测、飞书 OTP 恢复）
- 飞书进度通知（progress/complete/alert/paused）

**与 Claude Code 的关系**：Claude Code 是工程控制台（设计、维护、调试），Hermes Runner 是后台执行器。

---

## 2. 前置条件

### 2.1 环境检查

```bash
# 确认 bastion profile 已配置
python tools/agent.py profiles

# 确认 workflow.yaml 配置正确
python skills/ut/terminal-workflow/scripts/archive/supervisor_loop.py --validate
```

### 2.2 飞书配置（OTP 收信用）

确保 `.agents/feishu_config.json` 存在且包含 `app_id`、`app_secret`、`chat_id`：

```json
{
  "app_id": "cli_xxxxxxxxxxxx",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "chat_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

飞书应用需要 `im:message` 和 `im:message:read` 权限。

### 2.3 workflow.yaml bastion 配置

```yaml
bastion:
  managed_by: hermes
  profile: "t_h20"
  heartbeat_interval: 15
  otp_timeout: 300
  notify_on_disconnect: true
  auto_restart: true
```

---

## 3. 启动

### 3.1 新建运行

```bash
python skills/ut/terminal-workflow/scripts/hermes_runner.py \
  --workflow-yaml .agents/workflow.yaml
```

Runner 会：
1. 调用 `init_workflow_state.py` 初始化状态
2. 创建 `runs/ut-{timestamp}/` 运行目录
3. 检查 Bastion 连接，不可用时请求飞书 OTP
4. 启动心跳，进入 Stage 2-5 循环

### 3.2 断点续跑

```bash
python skills/ut/terminal-workflow/scripts/hermes_runner.py \
  --workflow-yaml .agents/workflow.yaml \
  --resume-from D:/workspace/apmm/runs/ut-20260612-101857
```

Runner 会：
1. 读取已有的 `workflow_state.json`
2. 从 `current_stage` 继续执行
3. 跳过已完成的 batch（检查 `batch_results.json` 是否存在）

### 3.3 通过 Hermes 启动

在 Hermes Agent 中加载 `ut/workflow` skill，Agent 识别意图后自动调用 `hermes_runner.py`。

### 3.4 Kanban 模式

设置 `workflow.yaml` 中 `kanban.enabled: true`，Runner 自动：

1. 检查 Hermes Agent、Board、Worker Profiles 是否就绪
2. 调用 `start_gateway.py` 启动 3 个 Gateway
3. 创建初始 Orchestrator 任务
4. 轮询 `hermes kanban stats` 直到完成
5. 飞书通知启动/完成/暂停事件

Kanban 前置条件见 [Kanban 集成指南](../kanban/README.md)。

---

## 4. OTP 交互流程

当 Bastion daemon 不可用时，Runner 自动请求 OTP：

```text
1. Runner 检测 daemon 断联
2. 生成 request_id（格式：otp-20260618-abc123）
3. 发送飞书卡片到配置的群聊
4. 用户在飞书回复：OTP otp-20260618-abc123 123456
5. Runner 接收 OTP，重启 daemon
6. Daemon 恢复后继续 workflow
```

### 4.1 飞书回复格式

```
OTP otp-20260618-abc123 123456
```

- 必须以 `OTP` 开头
- 必须包含完整的 `request_id`
- 6 位数字 OTP 码
- 300s 内有效

### 4.2 安全规则

- OTP 不写入任何日志文件
- OTP 使用后立即清除
- 每个 profile 同一时间只允许一个 active OTP request
- 不接受无 request_id 的裸 OTP

---

## 5. 状态文件

### 5.1 workflow_state.json bastion 字段

```json
{
  "bastion": {
    "status": "connected",
    "profile": "t_h20",
    "last_heartbeat_at": "2026-06-18T10:00:00+08:00",
    "otp_request_id": null,
    "last_disconnect_reason": null
  }
}
```

状态枚举：

| 状态 | 含义 |
|------|------|
| `connected` | daemon 可用 |
| `disconnected` | daemon 不可用 |
| `waiting_for_otp` | 已通知用户，等待飞书 OTP |
| `reconnecting` | 已收到 OTP，正在重启 daemon |
| `failed` | 重连失败，需要人工处理 |

### 5.2 暂停恢复

Runner 在以下条件暂停：

| 条件 | 阈值 | 恢复方式 |
|------|------|----------|
| 完成 | `pending_count == 0` | 正常结束 |
| 连续失败 | `consecutive_failures > 50` | 人工检查后 `--resume-from` |
| 高错误率 | `error_rate > 80%` | 人工检查后 `--resume-from` |
| Bastion 断联 | 心跳连续 2 次失败 | 飞书 OTP 自动恢复 |

暂停后 workflow_state.json 中 `flags.pause_requested` 为 `true`，`workflow.status` 为 `paused`。

恢复命令：
```bash
# 清除暂停标志后重新启动
python skills/ut/terminal-workflow/scripts/hermes_runner.py \
  --workflow-yaml .agents/workflow.yaml \
  --resume-from D:/workspace/apmm/runs/ut-20260612-101857
```

---

## 6. 排错

### 6.1 Bastion daemon 无法启动

```bash
# 手动检查 daemon 状态
python tools/agent.py -p t_h20 ping

# 手动启动 daemon（需要输入 OTP）
python tools/agent.py serve t_h20

# 使用 bastion_manager CLI 测试
python skills/ut/terminal-workflow/scripts/bastion_manager.py ping
python skills/ut/terminal-workflow/scripts/bastion_manager.py ensure --reason "manual test"
```

### 6.2 飞书 OTP 收不到

1. 检查 `feishu_config.json` 是否存在且配置正确
2. 确认飞书应用有 `im:message:read` 权限
3. 确认 `chat_id` 对应的群聊中已添加机器人
4. 手动测试飞书连接：
   ```bash
   python skills/ut/terminal-workflow/scripts/feishu_api.py
   ```

### 6.3 Workflow 状态不一致

```bash
# 从 manifest 重新计算 stats
python skills/ut/terminal-workflow/scripts/archive/supervisor_loop.py --update-stats
```

### 6.4 查看当前运行状态

```bash
python skills/ut/terminal-workflow/scripts/archive/supervisor_loop.py --check
```

### 6.5 Runner 意外退出

1. 检查 `workflow_state.json` 中的 `current_stage` 和 `iteration`
2. 使用 `--resume-from` 恢复
3. 如果状态损坏，删除 `workflow_state.json` 重新初始化

---

## 7. 飞书通知场景

| event | 触发条件 | 卡片颜色 |
|-------|---------|:---------:|
| `progress` | 每个 batch 完成 | 🟦 蓝色 |
| `complete` | `pending_count == 0` | 🟩 绿色 |
| `alert` | `error_rate > 30%` | 🟥 红色 |
| `paused` | 暂停（Bastion 断联/高错误率/连续失败） | 🟨 黄色 |

---

## 8. 相关文件

| 文件 | 说明 |
|------|------|
| `skills/ut/terminal-workflow/scripts/hermes_runner.py` | Runner 主脚本 |
| `skills/ut/terminal-workflow/scripts/bastion_manager.py` | Bastion 生命周期管理 |
| `skills/ut/terminal-workflow/scripts/feishu_api.py` | 飞书 API 封装 |
| `.agents/workflow.yaml` | Workflow 配置（含 bastion 节） |
| `skills/ut/terminal-workflow/workflow_state_schema.json` | 状态文件 Schema |
| `tasks/ut/docs/discussions/2026-06-18-hermes-runner-bastion-otp-design.md` | 设计文档 |

---

*创建日期: 2026-06-18*
