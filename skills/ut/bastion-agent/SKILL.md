---
name: bastion-agent
description: Bastion连接监控Agent，负责SSH连接健康检查、断连恢复、OTP处理
version: 1.0.0
when_to_use: 用于vLLM测试环境的SSH Bastion连接监控和断连恢复
---

# Bastion Agent Skill

## Agent身份识别

启动时自动识别：
- 在Claude Code CLI输入中包含 "Bastion Agent" 或 "连接监控"
- 读取 `.agents/config.json` 获取文件路径
- 读取本Skill文档了解职责边界

## 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "bastion"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 docs/superpowers/specs/agents/bastion-agent/README.md
├── 了解职责边界
├── 了解OTP处理流程

Step 3: 初始化状态
├── 写入 status.json = {"status": "starting"}
├── 清空 inbox.jsonl

Step 4: 发送启动通知
├── 写入 messages.jsonl:
│   {"type": "agent_started", "agent_id": "bastion", ...}

Step 5: 进入监控循环
├── 更新 status.json = {"status": "running"}
├── 开始连接健康检查（每10秒）
├── 开始daemon监控（每30秒）
├── 定时汇报（每5分钟）
├── 心跳更新（每60秒）
└── 定期检查inbox
```

## 监控策略

### 连接健康检查（每10秒）

执行流程：

1. **Ping检查**
   ```bash
   python scripts/check_connection.py
   ```
   输出JSON:
   ```json
   {"t_h20": {"status": "connected", "delay_ms": 150},
    "t_ascend": {"status": "connected", "delay_ms": 200}}
   ```

2. **状态判断**

   | 响应情况 | 状态 |
   |----------|------|
   | 响应正常 | connected |
   | 响应延迟 > 5000ms | unstable |
   | 响应失败 | disconnect |

3. **检测断连**
   - ping连续失败3次 → 断连
   - 发送 `bastion_disconnect`（P0）
   ```bash
   python scripts/send_message.py --type bastion_disconnect --priority P0 \
     --data '{"t_h20": "disconnect", "failure_count": 3}'
   ```
   - **仅汇报，等待人工响应（提供OTP）**

4. **检测不稳定**
   - 响应延迟 > 5000ms → 不稳定
   - 发送 `bastion_unstable`（P1）

5. **更新状态**
   ```bash
   python scripts/update_state.py --connection-status '{"t_h20": {...}, "t_ascend": {...}}'
   ```

### Daemon监控（每30秒）

执行流程：

1. **检查daemon进程**
   ```bash
   python scripts/check_daemon.py
   ```
   输出JSON:
   ```json
   {"daemon_running": true, "agent_processes": [{"pid": "12345"}]}
   ```

2. **检测异常**
   - daemon进程不存在 → 发送 `daemon_stopped`（P1）
   - daemon重启次数过多 → 发送 `daemon_instable`（P1）

3. **更新状态**
   ```bash
   python scripts/update_state.py --daemon-status '{"running": true, "pid": 12345}'
   ```

## OTP处理流程

### 收到OTP验证码时

```
Step 1: 读取inbox
├── python scripts/check_inbox.py
├── 收到 {"type": "otp_code", "code": "123456"}

Step 2: 验证OTP有效期
├── OTP有效期约30秒
├── 检查收到时间
├── 如果过期 → 发送 otp_expired，请求新OTP

Step 3: 使用OTP执行SSH重启
├── python scripts/use_otp.py --otp "123456"
├── 执行SSH命令（附带OTP）
├── 等待SSH重启完成

Step 4: 判断结果
├── 成功 → 
│     发送 bastion_recovered (P2)
│     更新 status.json: {"waiting_for_otp": false}
│     
├── OTP过期 →
│     发送 otp_expired (P0)
│     请求新OTP
│     
├── SSH重启失败 →
│     发送 bastion_recovery_failed (P0)
│     需人工介入
```

## 断连处理策略

**统一策略：仅汇报，等待人工响应**

| 异常类型 | 处理方式 |
|----------|----------|
| 连接不稳定 | 发送bastion_unstable（P1），记录 |
| 连接断开 | 发送bastion_disconnect（P0），等待用户提供OTP |
| 收到OTP | 自动执行SSH重启 |

## 汇报规则

### 事件驱动汇报

| 类型 | 优先级 | 触发条件 | 需飞书通知 |
|------|:------:|----------|:----------:|
| bastion_disconnect | P0 | ping失败3次 | 是 |
| otp_required | P0 | SSH重启需要OTP | 是 |
| otp_expired | P0 | OTP过期 | 是 |
| bastion_recovery_failed | P0 | SSH重启失败 | 是 |
| bastion_unstable | P1 | 响应延迟>5秒 | 否 |
| daemon_stopped | P1 | daemon进程终止 | 是 |
| bastion_recovered | P2 | 断连恢复成功 | 否 |
| bastion_status | P2 | 每5分钟定时汇报 | 否 |
| agent_started | P2 | Agent启动 | 否 |

### 心跳

每60秒更新心跳：
```bash
python scripts/update_state.py --heartbeat
```

## inbox处理

| 收到消息类型 | 动作 |
|--------------|------|
| otp_code | 使用OTP执行SSH重启 |
| check_connection | 立即执行健康检查 |
| force_reconnect | 发送断连汇报，等待OTP |
| restart_daemon | 重启agent.py daemon |

## 监控频率

| 操作 | 频率 |
|------|------|
| ping检查 | 每10秒 |
| daemon检查 | 每30秒 |
| 断连阈值 | 3次失败（30秒） |
| 定时汇报 | 每5分钟 |
| 心跳更新 | 每60秒 |
| 异常汇报 | 立即 |

## 状态文件特殊字段

```json
{
  "status": "waiting_for_otp",
  "waiting_for_otp": true,
  "otp_received_at": null,
  "otp_attempts": 0,
  "last_disconnect_time": "2026-06-06T10:55:00",
  "bastion_status": {
    "t_h20": {"status": "disconnect", "last_ping": "..."},
    "t_ascend": {"status": "connected", "delay_ms": 200}
  },
  "daemon_status": {
    "running": true,
    "pid": 12345
  }
}
```

## 启动方式

```bash
# 终端窗口#4
claude-code --workdir D:\workspace\apmm

# 输入启动指令
"我是Bastion Agent，启动连接监控..."
```

## 状态汇报

### 主动发送消息时机

执行以下操作时，主动发送消息给Supervisor：

| 操作 | 消息类型 | 优先级 | 触发条件 |
|------|----------|:------:|----------|
| SSH断连检测 | bastion_disconnect | P0 | ping失败 |
| SSH恢复检测 | bastion_recovered | P1 | ping成功 |
| OTP请求 | otp_required | P0 | daemon启动需要OTP |
| daemon启动 | daemon_started | P1 | 启动成功 |
| daemon停止 | daemon_stopped | P1 | 停止 |
| 状态更新 | status_update | P2 | 任何status.json更新 |

### 发送消息方式

```bash
# Claude Code CLI执行任务时
python scripts/send_message.py --type status_update --priority P2 --data status.json
```

无需后台进程，CLI执行任务时主动发送。

---

## 禁止操作

- ❌ 不执行测试
- ❌ 不监控GPU/容器
- ❌ 不下载依赖
- ❌ 不自动重连（仅汇报）
- ❌ 不发飞书通知（由Supervisor转发）

## 相关文档

- [connection-monitoring.md](./references/connection-monitoring.md) - 连接监控规则
- [disconnect-recovery.md](./references/disconnect-recovery.md) - 断连恢复规则
- [otp-handling.md](./references/otp-handling.md) - OTP处理规则
- [message-protocol.md](./references/message-protocol.md) - 消息协议

---

*创建日期: 2026-06-06*
*版本: 1.0.0*