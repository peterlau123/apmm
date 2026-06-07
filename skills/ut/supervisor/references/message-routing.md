# 消息路由规则

## 消息来源

| 来源 | 消息队列位置 |
|------|-------------|
| Bastion | .agents/bastion/messages.jsonl |
| Runner | .agents/unit-test-runner/messages.jsonl |
| Environment | .agents/environment/messages.jsonl |
| Supervisor Inbox | .agents/supervisor/inbox.jsonl |
| 飞书 | 飞书API实时监听 |

## 路由规则表

| 消息类型 | 来源 | 路由目标 | 动作 |
|----------|------|----------|------|
| bastion_disconnect | Bastion | 无 | 飞书通知OTP请求 |
| otp_required | Bastion | 无 | 飞书通知OTP请求 |
| bastion_recovered | Bastion | 无 | 飞书通知恢复 |
| runner_stalled | Runner | 无 | 飞书通知停滞 |
| runner_paused | Runner | 无 | 飞书通知暂停 |
| runner_stopped | Runner | 无 | 飞书通知停止 |
| progress_milestone | Runner | 无 | 飞书进度通知 |
| phase_complete | Runner | 无 | 飞书完成通知 |
| all_complete | Runner | 无 | 飞书全部完成 |
| gpu_occupied | Environment | Runner | 转发，Runner调整GPU |
| gpu_intrusion | Environment | 无 | 飞书通知GPU抢占 |
| container_error | Environment | 无 | 飞书通知容器异常 |
| dependency_request | Runner | Environment | 转发，Environment下载 |
| dependency_ready | Environment | Runner | 转发，Runner继续 |
| feishu_otp | 飞书 | Bastion | 转发OTP给Bastion |
| feishu_command | 飞书 | 对应Agent | 解析并转发 |

## 优先级处理

| 优先级 | 处理方式 |
|:------:|----------|
| P0 | 立即处理，飞书实时通知 |
| P1 | 下一轮轮询处理，飞书通知 |
| P2 | 定期汇总通知 |

## 消息处理流程

```
1. 读取消息队列
   ├── supervisor_message_poll.py
   └── 按时间戳过滤新消息

2. 分类处理
   ├── P0消息 → 立即发送飞书
   ├── P1消息 → 记录，下一轮处理
   └── P2消息 → 汇总，定期通知

3. 路由转发
   ├── 需要转发 → 写入目标Agent inbox
   ├── 无需转发 → 处理完成标记

4. 更新处理记录
   └── processed_messages.jsonl
```

## 飞书消息格式

### P0紧急消息
```json
{
  "msg_type": "text",
  "content": {"text": "🔴 [P0] bastion_disconnect\nSSH连接断开\n需要启动daemon: python agent.py serve t_h20\n请回复OTP验证码"}
}
```

### P1重要消息
```json
{
  "msg_type": "text",
  "content": {"text": "✅ [P1] phase_complete\nPhase 1测试完成\n总计: 6872测试\n通过: 6293\n失败: 579"}
}
```

### P2普通消息
```json
{
  "msg_type": "text",
  "content": {"text": "📊 [P2] progress_milestone\n测试进度: 1000/6872\n通过率: 97.3%"}
}
```

---

*创建日期: 2026-06-06*