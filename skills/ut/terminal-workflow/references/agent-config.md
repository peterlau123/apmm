# Agent配置

## 文件路径配置

配置文件: `.agents/config.json`

```json
{
  "agents_dir": "D:/workspace/apmm/.agents",
  "feishu_config": ".agents/feishu_config.json",
  "agents": {
    "workflow": {
      "id": "supervisor",
      "type": "hermes",
      "status_file": ".agents/workflow/status.json",
      "heartbeat_file": ".agents/workflow/heartbeat.json",
      "inbox_file": ".agents/workflow/inbox.jsonl",
      "messages_file": ".agents/workflow/messages.jsonl",
      "skill_file": "skills/workflow/SKILL.md",
      "spec_file": "docs/superpowers/specs.agents/workflow-agent/README.md"
    },
    "bastion": {
      "id": "bastion",
      "type": "claude-code",
      "status_file": ".agents/bastion/status.json",
      "skill_file": "skills/bastion-agent/SKILL.md"
    },
    28|    "unit-test-executor": {
      29|      "id": "unit-test-executor",
      "type": "claude-code",
      31|      "status_file": ".agents/unit-test-executor/status.json",
      "skill_file": "skills/ut/unit-test-executor/SKILL.md"
    },
    "environment": {
      "id": "environment",
      "type": "claude-code",
      "status_file": ".agents/environment/status.json",
      "skill_file": "skills/environment-agent/SKILL.md"
    }
  }
}
```

## Supervisor脚本路径

| 脚本 | 位置 | 功能 |
|------|------|------|
| supervisor_loop.py | skills/supervisor/scripts/ | 主循环脚本 |
| supervisor_message_poll.py | skills/supervisor/scripts/ | 消息轮询 |
| supervisor_status_check.py | skills/supervisor/scripts/ | 状态检查 |
| supervisor_feishu_listen.py | skills/supervisor/scripts/ | 飞书监听 |
| feishu_api.py | skills/supervisor/scripts/ | 飞书API封装 |
| message_router.py | skills/supervisor/scripts/ | 消息路由辅助 |
| check_all_agents.py | skills/supervisor/scripts/ | Agent状态检查 |

## 状态文件结构

### status.json
```json
{
  "agent_id": "supervisor",
  "agent_type": "hermes",
  "status": "monitoring",
  "started_at": "2026-06-06T19:18:00",
  "last_update": "2026-06-06T20:08:00",
  "agents_status": {
    "bastion": {"status": "running", "last_heartbeat": "..."},
    "runner": {"status": "running", "last_heartbeat": "..."},
    "environment": {"status": "running", "last_heartbeat": "..."}
  },
  "feishu_connected": true,
  "cron_job_running": true,
  "current_task": "monitoring"
}
```

### heartbeat.json
```json
{
  "timestamp": "2026-06-06T12:08:05Z",
  "source": "supervisor_loop",
  "pid": 12345
}
```

## 消息文件结构

### inbox.jsonl
```json
{"type": "feishu_otp", "otp": "123456", "timestamp": "..."}
{"type": "feishu_command", "command": "pause", "target": "runner"}
```

### messages.jsonl
```json
{"type": "agent_started", "agent_id": "supervisor", "timestamp": "..."}
{"type": "agent_timeout", "agent_id": "runner", "timestamp": "..."}
```

---

*创建日期: 2026-06-06*