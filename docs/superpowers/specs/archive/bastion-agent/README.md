# Bastion Agent 设计

> **⚠️ DEPRECATED - 此Agent已移除**
> 
> **最新方案**: [../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)
> 
> Bastion Agent 已移除，职责合并到 Runner Agent：
> - 连接监控 → Runner通过agent.py直接连接
> - 断连恢复 → Runner处理重连逻辑
> - OTP处理 → Runner接收飞书OTP指令

---

## 原设计（已废弃）

> **Agent协同系统 - Bastion Agent (Claude Code)**
> **职责: Bastion连接监控、断连恢复、OTP处理**
> **创建日期: 2026-06-06**

---

## Agent信息

| 属性 | 值 |
|------|-----|
| Agent ID | `bastion` |
| Agent类型 | Claude Code CLI |
| 终端窗口 | #4 |
| 状态文件 | `.agents/bastion/status.json` |
| 消息文件 | `.agents/bastion/messages.jsonl` |
| 接收文件 | `.agents/bastion/inbox.jsonl` |
| Spec文件 | `docs/superpowers/specs/agents/bastion-agent/README.md` |

---

## 核心职责

```
┌─────────────────────────────────────────────────────────────────┐
│                    Bastion Agent职责                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ✅ Daemon监控                                                   │
│  ├── 检查agent.py daemon运行状态                                 │
│  ├── 监控daemon进程                                              │
│  └── 检测daemon异常                                              │
│                                                                  │
│  ✅ 连接健康检查                                                 │
│  ├── 定期ping t_h20                                              │
│  ├── 定期ping t_ascend                                           │
│  ├── 记录连接延迟                                                │
│  └── 检测连接不稳定                                              │
│                                                                  │
│  ✅ 断连恢复                                                     │
│  ├── 检测完全断连                                                │
│  ├── 尝试自动重连                                                │
│  ├── 请求OTP验证码（SSH重启需要）                                 │
│  └── 使用OTP重启SSH                                              │
│                                                                  │
│  ✅ OTP处理                                                      │
│  ├── 接收Supervisor转发的OTP验证码                               │
│  ├── 使用OTP执行SSH重启                                          │
│  ├── 处理OTP过期                                                 │
│  │  （请求新OTP）                                                │
│                                                                  │
│  ❌ 不负责                                                       │
│  ├── 不执行测试                                                  │
│  ├── 不监控GPU/容器                                              │
│  ├── 不下载依赖                                                  │
│  ├── 不发飞书通知                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 启动方式

```bash
# 启动Claude Code CLI
claude-code --workdir D:\workspace\apmm

# 启动后输入
"我是Bastion Agent，启动连接监控..."
```

### 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "bastion"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 bastion-agent/README.md
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
├── 开始连接健康检查
├── 定期检查inbox
└── 定期汇报状态
```

---

## 主循环逻辑

### 连接健康检查（每10秒）

```
┌─────────────────────────────────────────────────────────────────┐
│                    连接健康检查流程                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Ping检查:                                                       │
│  ├── 执行: python agent.py -p t_h20 ping                        │
│  ├── 执行: python agent.py -p t_ascend ping                     │
│  ├── 记录响应时间                                                │
│                                                                  │
│  状态判断:                                                       │
│  ├── 响应正常 → status = "connected"                            │
│  ├── 响应延迟 > 5s → status = "unstable"                        │
│  ├── 响应失败 → status = "disconnect"                           │
│                                                                  │
│  问题汇报:                                                       │
│  ├── 连接不稳定 → 发送 bastion_unstable                         │
│  ├── 完全断连 → 发送 bastion_disconnect                         │
│                                                                  │
│  更新状态:                                                       │
│  ├── 更新status.json的bastion_status字段                         │
│  ├── 定期发送bastion_status                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 断连恢复流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    断连恢复流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: 检测断连                                                │
│  ├── ping连续失败3次                                             │
│  ├── 发送 bastion_disconnect 消息                               │
│  ├── 更新 status.json: {"status": "reconnecting"}               │
│                                                                  │
│  Step 2: 尝试自动重连                                            │
│  ├── 执行: python agent.py restart                              │
│  ├── 等待30秒                                                    │
│  ├── 再次ping                                                    │
│                                                                  │
│  Step 3: 判断结果                                                │
│  ├── 成功 → 发送 bastion_recovered                              │
│  │        更新 status.json: {"status": "running"}               │
│  │                                                              │
│  ├── 失败（需要SSH重启）→                                        │
│  │     更新 status.json: {"waiting_for_otp": true}              │
│  │     发送 otp_required 消息                                   │
│  │     Supervisor发飞书请求OTP                                  │
│  │                                                              │
│  ├── 失败（其他原因）→                                           │
│  │     发送 bastion_recovery_failed                             │
│  │     需人工介入                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## OTP处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    OTP处理流程                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: 收到OTP验证码                                           │
│  ├── inbox.jsonl: {"type": "otp_code",                          │
│  │                 "code": "123456",                             │
│  │                 "from": "supervisor"}                         │
│  ├── 记录收到时间                                                │
│  │  OTP有效期约30秒                                              │
│                                                                  │
│  Step 2: 使用OTP执行SSH重启                                      │
│  ├── 执行SSH命令（附带OTP）                                      │
│  │  具体命令根据SSH配置而定                                      │
│  ├── 等待SSH重启完成                                             │
│                                                                  │
│  Step 3: 判断结果                                                │
│  ├── 成功 →                                                      │
│  │     发送 bastion_recovered                                   │
│  │     更新 status.json: {"waiting_for_otp": false}             │
│  │     Supervisor通知Runner继续                                  │
│  │                                                              │
│  ├── OTP过期 →                                                   │
│  │     发送 otp_expired                                         │
│  │     Supervisor发飞书请求新OTP                                 │
│  │                                                              │
│  ├── SSH重启失败 →                                               │
│  │     发送 bastion_recovery_failed                             │
│  │     需人工介入                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 汇报给Supervisor的场景

| 消息类型 | 触发条件 | 优先级 | 数据内容 |
|----------|----------|:------:|----------|
| `agent_started` | Agent启动完成 | P2 | 启动时间 |
| `bastion_unstable` | Ping延迟 > 5秒 | P1 | delay_ms, consecutive_slow |
| `bastion_disconnect` | Ping失败3次 | P0 | last_ping_time, failure_count |
| `otp_required` | SSH重启需要OTP | P0 | reason, waiting_for_otp |
| `otp_expired` | OTP过期 | P0 | expired_code_time |
| `bastion_recovered` | 断连恢复成功 | P2 | reconnect_time, method |
| `bastion_recovery_failed` | 恢复失败 | P0 | failure_reason, need_human |
| `bastion_status` | 定时汇报（每分钟） | P2 | t_h20状态, t_ascend状态 |

---

## inbox消息处理

| 收到消息类型 | 动作 |
|--------------|------|
| `otp_code` | 使用OTP执行SSH重启 |
| `check_connection` | 立即执行健康检查 |
| `force_reconnect` | 强制执行重连 |
| `restart_daemon` | 重启agent.py daemon |

---

## 需人工介入的场景

| 场景 | 原因 | 用户操作 |
|------|------|----------|
| SSH daemon停止 | daemon进程终止 | 手动重启SSH，输入OTP |
| Bastion服务器不可达 | 网络问题 | 检查VPN/网络 |
| OTP连续过期 | 时间不够 | 手动提供新OTP |
| SSH重启失败 | 权限/配置问题 | 手动处理SSH |

---

## 终端用户指令

用户在Bastion终端可直接输入：

| 指令 | 动作 |
|------|------|
| `我的状态` | 输出status.json |
| `连接状态` | 输出t_h20/t_ascend连接详情 |
| `重连` | 手动触发重连尝试 |
| `检查连接` | 立即执行健康检查 |
| `汇报状态` | 手动发送bastion_status |

---

## 状态文件特殊字段

```json
{
  "status": "waiting_for_otp",
  "waiting_for_otp": true,
  "otp_received_at": null,
  "otp_attempts": 0,
  "last_disconnect_time": "2026-06-06T10:55:00",
  "bastion_status": {
    "t_h20": "disconnected",
    "t_ascend": "connected"
  }
}
```

---

## 相关文档

- [connection-monitoring.md](./connection-monitoring.md) - 连接监控详细设计
- [disconnect-recovery.md](./disconnect-recovery.md) - 断连恢复详细设计
- [otp-handling.md](./otp-handling.md) - OTP处理详细设计

---

*创建日期: 2026-06-06*