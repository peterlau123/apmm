# 消息协议

## 消息格式

所有消息写入 `.agents/runner/messages.jsonl`，每行一个JSON：

```json
{
  "type": "<消息类型>",
  "priority": "P0/P1/P2",
  "timestamp": "2026-06-06T10:30:00",
  "agent_id": "unit-test-runner",
  "request_id": "req-001",
  "data": { ... }
}
```

## 发送方式

```bash
python scripts/send_message.py --type <type> --priority <p> --data '<json>'
```

## 消息类型列表

### P0 紧急消息

| 类型 | 触发条件 | 数据内容 |
|------|----------|----------|
| bastion_disconnect | ping失败3次 | consecutive_failures, last_ping, affected_workers |
| gpu_occupied | GPU被占用 | idle_gpus, occupied_gpus, occupying_pids |

### P1 重要消息

| 类型 | 触发条件 | 数据内容 |
|------|----------|----------|
| dependency_request | ImportError | dependency_type, name, affected_tests, test_files |
| cpu_overload | CPU>85% | cpu_usage, occupying_processes |
| phase_complete | Phase/Round完成 | phase, round, stats, duration_hours |
| all_complete | 全部完成 | total_tests, duration_hours, final_stats |
| fallback_triggered | 执行fallback | fallback_type, reason, action_taken |

### P2 常规消息

| 类型 | 触发条件 | 数据内容 |
|------|----------|----------|
| progress_milestone | 每100测试 | completed, total, passed, failed, phase, round |
| agent_started | Agent启动 | started_at, config_paths |

## 消息示例

### bastion_disconnect

```json
{
  "type": "bastion_disconnect",
  "priority": "P0",
  "timestamp": "2026-06-06T10:30:00",
  "agent_id": "unit-test-runner",
  "data": {
    "consecutive_failures": 3,
    "last_ping": "2026-06-06T10:29:30",
    "current_status": "disconnected",
    "affected_workers": [1, 2, 3],
    "request": "please_check_connection"
  }
}
```

### dependency_request

```json
{
  "type": "dependency_request",
  "priority": "P1",
  "timestamp": "2026-06-06T10:35:00",
  "agent_id": "unit-test-runner",
  "data": {
    "dependency_type": "model",
    "name": "meta-llama/Llama-3.2-1B-Instruct",
    "affected_tests": 42,
    "test_files": ["tests/models/test_llama.py"],
    "request": "please_download"
  }
}
```

### progress_milestone

```json
{
  "type": "progress_milestone",
  "priority": "P2",
  "timestamp": "2026-06-06T10:40:00",
  "agent_id": "unit-test-runner",
  "data": {
    "phase": 1,
    "round": 1,
    "completed": 4200,
    "total": 7740,
    "passed": 3845,
    "failed": 312,
    "error": 43,
    "progress_percent": 54.3
  }
}
```

---

*创建日期: 2026-06-06*