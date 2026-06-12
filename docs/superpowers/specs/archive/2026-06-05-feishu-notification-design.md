# Feishu Notification Integration Design

> **⚠️ DEPRECATED - 此文档已过时**
> 
> **最新方案**: [../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)
> 
> 飞书通知现由 Supervisor Agent 统一负责，具体实现见 `supervisor-agent/README.md`

---

## 原设计（已废弃）

> **Real-time Progress Notifications for Test Automation System**
> **Send milestone, error, phase, and recovery notifications via Feishu (飞书/Lark)**
> **Created: 2026-06-05**

---

## Overview

### Problem Statement

During test execution, user needs real-time notifications:
- Progress tracking without constantly checking terminal
- Immediate alerts when errors occur
- Status updates when phases complete
- Recovery notifications after disconnect

### Solution

Integrate Feishu notification module with test automation scripts:
- Send rich text cards to group chat
- Configurable notification scenarios
- Non-blocking design (notification failure doesn't stop tests)

---

## Notification Scenarios

| Scenario | Trigger | Priority |
|----------|---------|:--------:|
| **Milestone** | Every 100 tests | Info |
| **Error Threshold** | 5 consecutive errors | Alert |
| **Phase Complete** | Round/Phase transition | Info |
| **Disconnect Recovery** | Network restored | Warning |
| **All Complete** | Execution finished | Success |

---

## Module Architecture

### feishu_notifier.py Structure

```
feishu_notifier.py
├── FeishuConfig (dataclass)
│   ├── app_id: str
│   ├── app_secret: str
│   ├── chat_id: str
│   ├── user_id: str
│   ├── milestone_interval: int = 100
│   └── agent_name: str = "Unit Test Runner Agent"
│
├── FeishuNotifier (main class)
│   ├── __init__(config)
│   ├── get_tenant_access_token() → str
│   ├── send_message(content) → bool
│   ├── send_card(title, elements) → bool
│   ├── notify_milestone(progress_data)
│   ├── notify_error_threshold(error_data)
│   ├── notify_phase_complete(phase_data)
│   ├── notify_disconnect_recovery(recovery_data)
│   ├── notify_all_complete(final_data)
│   ├── test_connection() → bool
│   └── from_config(config_path) → FeishuNotifier
│
├── CardTemplateBuilder
│   ├── build_milestone_card(data)
│   ├── build_error_card(data)
│   ├── build_phase_card(data)
│   ├── build_recovery_card(data)
│   ├── build_complete_card(data)
│   ├── _build_progress_bar(percent)
│   └── _build_stats_table(stats)
│
└── CLI Interface
    ├── --test: Test connection
    ├── --send-demo: Send demo card
    └── --config: Show current config
```

---

## Feishu API Integration

### Authentication Flow

```
Step 1: Get tenant_access_token
├── POST https://open.feishu.cn/open-api/auth/v3/
│       tenant_access_token/internal
├── Body: {"app_id": "...", "app_secret": "..."}
├── Response: {"tenant_access_token": "t-xxx", "expire": 7200}
└── Cache: Token valid for 2 hours, cache to avoid frequent requests

Step 2: Send Message
├── POST https://open.feishu.cn/open-api/im/v1/
│       messages?receive_id_type=chat_id
├── Headers: Authorization: Bearer t-xxx
├── Body: {"receive_id": "oc_xxx", 
│           "msg_type": "interactive",
│           "content": "{...card json...}"}
└── Response: {"code": 0, "msg": "success"}
```

### API Code Structure

```python
class FeishuNotifier:
    BASE_URL = "https://open.feishu.cn/open-api"
    
    def get_tenant_access_token(self) -> str:
        """Get tenant_access_token with caching"""
        if self._token and not self._token_expired():
            return self._token
        
        response = requests.post(
            f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.app_id, 
                  "app_secret": self.config.app_secret}
        )
        data = response.json()
        self._token = data["tenant_access_token"]
        self._token_expire_time = time.time() + data["expire"] - 60
        return self._token
    
    def send_card(self, title: str, elements: list) -> bool:
        """Send interactive card message"""
        token = self.get_tenant_access_token()
        card_content = self._build_card_json(title, elements)
        
        response = requests.post(
            f"{self.BASE_URL}/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": self.config.chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card_content)
            }
        )
        return response.json().get("code") == 0
```

---

## Card Templates

### Milestone Card

```json
{
  "type": "interactive",
  "card": {
    "header": {
      "title": { "tag": "plain_text", "content": "📊 测试进度里程碑" },
      "template": "blue"
    },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**Phase**: 1 Round 1\n**进度**: 4,200 / 7,740 (54.3%)\n**剩余**: 3,540 tests\n**预计**: ~1.2 小时" }
      },
      { "tag": "hr" },
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "统计:\n✅ Passed: 2,845\n❌ Failed: 312\n⚠️ Error: 156\n⏭️ Skip: 87" }
      },
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "Workers: 3 运行中 | Batch: batch_20260605_1030" }
      },
      { "tag": "hr" },
      { "tag": "note", "elements": [
        { "tag": "plain_text", "content": "🕐 2026-06-05 10:30:15" },
        { "tag": "plain_text", "content": "🤖 Unit Test Runner Agent" }
      ]}
    ]
  }
}
```

### Error Threshold Card

```json
{
  "type": "interactive",
  "card": {
    "header": {
      "title": { "tag": "plain_text", "content": "⚠️ 错误阈值触发" },
      "template": "red"
    },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md", 
        "content": "**触发原因**: 连续 5 个错误\n**测试文件**: tests/quantization/test_marlin.py\n**错误类型**: D-依赖缺失 (wrap_triton)\n**跳过测试**: 42 个" }
      },
      { "tag": "hr" },
      { "tag": "note", "elements": [
        { "tag": "plain_text", "content": "🕐 2026-06-05 10:35:22" },
        { "tag": "plain_text", "content": "🤖 Unit Test Runner Agent" }
      ]}
    ]
  }
}
```

### Phase Complete Card

```json
{
  "type": "interactive",
  "card": {
    "header": {
      "title": { "tag": "plain_text", "content": "🎉 Round 完成" },
      "template": "blue"
    },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**Phase**: 1\n**Round**: 1\n**执行测试**: 7,740\n**通过率**: 89.2%\n\n统计:\n- ✅ Passed: 6,880\n- ❌ Failed: 580\n- ⚠️ Error: 420\n- ⏭️ Skip: 160" }
      },
      { "tag": "hr" },
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**下一步**: 准备 Round 2，下载关键模型" }
      },
      { "tag": "hr" },
      { "tag": "note", "elements": [
        { "tag": "plain_text", "content": "🤖 Unit Test Runner Agent" }
      ]}
    ]
  }
}
```

### Disconnect Recovery Card

```json
{
  "type": "interactive",
  "card": {
    "header": {
      "title": { "tag": "plain_text", "content": "🔄 断连恢复" },
      "template": "yellow"
    },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**断连时间**: 2026-06-05 12:00:00\n**恢复时间**: 2026-06-05 14:30:00\n**远程完成**: 500 tests\n**恢复耗时**: < 30s" }
      },
      { "tag": "hr" },
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**当前进度**: 已同步，继续执行" }
      },
      { "tag": "hr" },
      { "tag": "note", "elements": [
        { "tag": "plain_text", "content": "🤖 Unit Test Runner Agent" }
      ]}
    ]
  }
}
```

### All Complete Card

```json
{
  "type": "interactive",
  "card": {
    "header": {
      "title": { "tag": "plain_text", "content": "🏆 测试执行完成" },
      "template": "green"
    },
    "elements": [
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**总执行**: 31,947 tests\n**总耗时**: 22.5 小时\n**通过率**: 87.3%\n\n最终统计:\n- ✅ Passed: 27,845\n- ❌ Failed: 2,880\n- ⚠️ Error: 1,102\n- ⏭️ Skip: 120" }
      },
      { "tag": "hr" },
      { "tag": "div", "text": { "tag": "lark_md",
        "content": "**Issues 发现**: 45 个\n**报告位置**: docs/reports/test_summary.md" }
      },
      { "tag": "hr" },
      { "tag": "note", "elements": [
        { "tag": "plain_text", "content": "🤖 Unit Test Runner Agent" }
      ]}
    ]
  }
}
```

---

## Integration Points

### test_scheduler.py Integration

```python
from feishu_notifier import FeishuNotifier, FeishuConfig

class Scheduler:
    def __init__(self, config: SchedulerConfig):
        # Load Feishu config
        feishu_config_path = work_dir / "feishu_config.json"
        if feishu_config_path.exists():
            self.feishu_notifier = FeishuNotifier.from_config(feishu_config_path)
        else:
            self.feishu_notifier = None
            logger.info("Feishu notifier disabled (no config)")
    
    def run_batch(self, dry_run=False):
        # ... execute batch ...
        
        # Milestone notification every 100 tests
        completed = self.state.phase1_status.completed
        if completed > 0 and completed % 100 == 0:
            if self.feishu_notifier:
                self.feishu_notifier.notify_milestone({
                    "phase": self.phase_manager.get_current_phase(),
                    "completed": completed,
                    "total": self.state.phase1_status.total,
                    "stats": self.manifest["statistics"],
                    "workers": len(self.remote_processes),
                    "batch_id": batch_id
                })
    
    def advance_phase(self):
        # ... phase transition ...
        if self.feishu_notifier:
            self.feishu_notifier.notify_phase_complete({
                "phase": old_phase,
                "round": round_num,
                "stats": phase_stats
            })
```

### batch_test_runner.py Integration

```python
def handle_results(self, results):
    # ... process results ...
    
    if self.consecutive_errors >= self.error_threshold:
        if self.feishu_notifier:
            self.feishu_notifier.notify_error_threshold({
                "trigger": f"连续 {self.consecutive_errors} 个错误",
                "test_file": current_file,
                "error_type": error_category,
                "tests_skipped": remaining_in_file
            })
```

---

## Configuration

### feishu_config.json

```json
{
  "app_id": "cli_aa951cb0dfb9dbda",
  "app_secret": "rTOni1va857lni9DQKn6Pd1EOPP8nYJ0",
  "chat_id": "oc_2e75db818ac1792238037a704b4d32d3",
  "user_id": "ou_755bfc83496581afd1b5e14204f06ace",
  "milestone_interval": 100,
  "agent_name": "Unit Test Runner Agent"
}
```

### Security Notes

- File contains sensitive credentials (App Secret)
- Do NOT commit to git (add to .gitignore)
- Local use only
- Environment variables alternative available

---

## Error Handling

### Notification Failure Handling

| Error Type | Handling |
|------------|----------|
| Network error | Retry 3 times, 5s interval |
| Token expired | Auto-refresh and retry |
| Permission denied | Log error, don't interrupt tests |
| Config missing | Silently skip, tests continue |

### Logging

```
Success: [INFO] Feishu card sent: milestone
Failure: [WARN] Feishu send failed: token expired
Retry:   [INFO] Retrying... (2/3)
Disabled: [INFO] Feishu notifier disabled
```

### Non-blocking Principle

- Feishu notification is auxiliary feature
- Send failure does NOT affect test execution
- Optional async send (don't wait for response)

---

## Card Role Identifier

Every card includes agent signature at the bottom:

```
┌─────────────────────────────────────┐
│ 📊 测试进度里程碑                    │
│ ...                                 │
│ 🕐 2026-06-05 10:30:15               │
│ 🤖 Unit Test Runner Agent            │
└─────────────────────────────────────┘
```

---

## CLI Commands

```bash
# Test connection
python feishu_notifier.py --test

# Send demo card
python feishu_notifier.py --send-demo milestone

# Show config
python feishu_notifier.py --config
```

---

## File Locations

```
D:\workspace\apmm\vllm\2.5.1\ut\
├── feishu_config.json       # Config file (local, not committed)
└── scripts/
    └── feishu_notifier.py   # Notification module
```

---

## Success Criteria

| Criteria | Target |
|----------|:------:|
| Connection test success | ✅ |
| Milestone cards delivered | 100% |
| Error alerts immediate | < 10s |
| No test interruption | ✅ |
| Agent identifier visible | ✅ |

---

*Created: 2026-06-05*
*Status: Draft - Pending Approval*