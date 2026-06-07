# 断连恢复规则

## 断连处理策略

**策略：仅汇报，等待人工响应**

| 异常类型 | 处理方式 |
|----------|----------|
| 连接不稳定 | 发送bastion_unstable（P1），记录 |
| 连接断开 | 发送bastion_disconnect（P0），等待用户提供OTP |

## 断连恢复流程

```
Step 1: 检测断连
├── ping连续失败3次
├── 发送 bastion_disconnect (P0)
├── 更新 status.json: {"waiting_for_otp": true}

Step 2: 等待人工响应
├── Supervisor发飞书请求OTP
├── 用户通过飞书提供OTP
├── Supervisor转发otp_code到inbox

Step 3: 收到OTP
├── 检查inbox: {"type": "otp_code", "code": "123456"}
├── 验证OTP有效期（约30秒）

Step 4: 使用OTP执行SSH重启
├── 执行SSH命令（附带OTP）
├── 等待SSH重启完成

Step 5: 判断结果
├── 成功 → 发送 bastion_recovered (P2)
│         更新 status.json: {"waiting_for_otp": false}
│
├── OTP过期 → 发送 otp_expired (P0)
│            请求新OTP
│
├── SSH重启失败 → 发送 bastion_recovery_failed (P0)
│                需人工介入
```

## 需人工介入的场景

| 场景 | 原因 | 用户操作 |
|------|------|----------|
| SSH daemon停止 | daemon进程终止 | 手动重启SSH，输入OTP |
| Bastion服务器不可达 | 网络问题 | 检查VPN/网络 |
| OTP连续过期 | 时间不够 | 手动提供新OTP |
| SSH重启失败 | 权限/配置问题 | 手动处理SSH |

---

*创建日期: 2026-06-06*