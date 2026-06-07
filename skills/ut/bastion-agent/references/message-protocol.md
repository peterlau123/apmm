# 消息协议

## 消息格式

```json
{
  "type": "<消息类型>",
  "priority": "P0/P1/P2",
  "timestamp": "ISO-8601",
  "agent_id": "bastion",
  "data": { ... }
}
```

## 消息类型列表

### P0 紧急消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| bastion_disconnect | ping失败3次 | 是 |
| otp_required | SSH重启需要OTP | 是 |
| otp_expired | OTP过期 | 是 |
| bastion_recovery_failed | SSH重启失败 | 是 |

### P1 重要消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| bastion_unstable | 响应延迟>5秒 | 否 |
| daemon_stopped | daemon进程终止 | 是 |

### P2 常规消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| bastion_recovered | 断连恢复成功 | 否 |
| bastion_status | 每5分钟定时汇报 | 否 |
| agent_started | Agent启动 | 否 |

## inbox接收消息

| 类型 | 动作 |
|------|------|
| otp_code | 使用OTP执行SSH重启 |
| check_connection | 立即执行健康检查 |
| force_reconnect | 发送断连汇报，等待OTP |
| restart_daemon | 重启agent.py daemon |

---

*创建日期: 2026-06-06*