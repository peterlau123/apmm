# OTP处理规则

## OTP特性

| 属性 | 值 |
|------|------|
| 验证码长度 | 6位数字 |
| 有效期 | 约30秒 |
| 来源 | Google Authenticator |

## OTP处理策略

**策略：自动使用OTP执行SSH重启**

收到OTP后的处理流程：
1. 验证OTP有效期
2. 自动执行SSH重启命令
3. 等待重启结果
4. 汇报成功/失败

## OTP使用命令

```bash
python scripts/use_otp.py --otp "123456"
```

## OTP处理结果

| 结果 | 状态 | 后续动作 |
|------|------|----------|
| SSH重启成功 | success | 发送bastion_recovered，通知Runner继续 |
| OTP过期 | expired | 发送otp_expired，请求新OTP |
| SSH重启失败 | error | 发送bastion_recovery_failed，需人工介入 |

## OTP安全处理

- OTP验证码部分隐藏显示（只显示前2位）
- OTP不写入持久化日志
- OTP使用后立即失效

## OTP过期处理

如果OTP过期：
1. 发送 `otp_expired`（P0）
2. Supervisor发飞书请求新OTP
3. 等待用户提供新OTP

---

*创建日期: 2026-06-06*