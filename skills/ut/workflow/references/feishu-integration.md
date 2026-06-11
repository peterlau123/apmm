# 飞书集成说明

## 飞书配置

配置文件: `.agents/feishu_config.json`

```json
{
  "app_id": "cli_aa951cb0dfb9dbda",
  "app_secret": "rTOni1va857lni9DQKn6Pd1EOPP8nYJ0",
  "chat_id": "oc_2e75db818ac1792238037a704b4d32d3",
  "user_id": "ou_755bfc83496581afd1b5e14204f06ace"
}
```

## 飞书API

### 获取Token
```
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Body: {"app_id": "...", "app_secret": "..."}
Response: {"tenant_access_token": "t-xxx", "expire": 7200}
```

### 发送消息
```
POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id
Headers: Authorization: Bearer t-xxx
Body: {"receive_id": "chat_id", "msg_type": "text", "content": {"text": "..."}}
```

### 监听消息（ webhook或轮询）

当前使用轮询方式监听飞书群消息。

## 飞书监听脚本

脚本: `scripts/supervisor_feishu_listen.py`

功能:
- 持续监听飞书群消息
- 解析用户指令
- 写入supervisor inbox

## 用户指令解析

| 用户输入 | 解析结果 |
|----------|----------|
| `otp 123456` | {"type": "feishu_otp", "otp": "123456"} |
| `otp:123456` | {"type": "feishu_otp", "otp": "123456"} |
| `验证码 123456` | {"type": "feishu_otp", "otp": "123456"} |
| `check status` | {"type": "feishu_command", "command": "check_status"} |
| `pause runner` | {"type": "feishu_command", "command": "pause", "target": "runner"} |
| `resume runner` | {"type": "feishu_command", "command": "resume", "target": "runner"} |
| `stop runner` | {"type": "feishu_command", "command": "stop", "target": "runner"} |

## 消息ID追踪

- 记录已处理消息ID
- 避免重复处理同一条消息
- 存储在 `.agents/workflow/processed_feishu_ids.jsonl`

## 错误处理

| 错误 | 处理 |
|------|------|
| Token过期 | 重新获取Token |
| 发送失败 | 记录日志，下次重试 |
| 解析失败 | 跳过，记录原始消息 |

---

*创建日期: 2026-06-06*