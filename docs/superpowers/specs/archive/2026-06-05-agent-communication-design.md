# Agent Communication Design

> **⚠️ DEPRECATED - 此文档已过时**
> 
> **最新方案**: [../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)
> 
> 此文档基于原四Agent架构设计，新架构已简化为双Agent（Supervisor + Runner），
> 通信机制也已简化为单一消息通道。

---

## 原设计（已废弃）

> **Inter-Agent Communication via Shared Files**
> **Unit Test Runner Agent ↔ Supervisor Agent**
> **Created: 2026-06-05**

---

## Overview

### Problem Statement

During test execution, issues arise that require coordination:
- Bastion SSH instability/disconnect
- GPU resources occupied by other processes
- CPU overloaded by other processes
- Dependencies/models missing

These issues need Supervisor Agent intervention to coordinate with other agents or human operators.

### Solution

Shared file communication with Feishu backup escalation:
- Runner Agent writes requests to `.agent_comm/requests/`
- Supervisor Agent reads and responds to `.agent_comm/responses/`
- Timeout triggers Feishu escalation for human intervention
- Autonomous fallback when Supervisor unavailable

---

## Request Types

### Summary

| Type | Trigger | Priority | Timeout | Fallback |
|------|---------|:--------:|:-------:|----------|
| **bastion_disconnect** | SSH ping fail 3x | P0 | 60s | Pause, retry every 30s |
| **gpu_occupied** | No idle GPU | P0 | 60s | Reduce workers to 1 |
| **dependency_request** | ImportError/model missing | P1 | 120s | Skip related tests |
| **cpu_overload** | CPU > 85% | P1 | 120s | Reduce workers to 1 |

---

## Module Architecture

### agent_comm.py Structure

```
agent_comm.py
├── CommConfig (dataclass)
│   ├── comm_dir: Path = .agent_comm/
│   ├── request_dir: Path = requests/
│   ├── response_dir: Path = responses/
│   ├── processed_dir: Path = processed/
│   ├── p0_timeout: int = 60
│   ├── p1_timeout: int = 120
│   └── poll_interval: int = 5
│
├── RequestType (enum)
│   ├── BASTION_DISCONNECT = "bastion_disconnect"
│   ├── DEPENDENCY_REQUEST = "dependency_request"
│   ├── GPU_OCCUPIED = "gpu_occupied"
│   ├── CPU_OVERLOAD = "cpu_overload"
│
├── AgentCommunicator (main class)
│   ├── __init__(config, feishu_notifier=None)
│   ├── send_request(request_type, data) → request_id
│   ├── wait_response(request_id) → response | None
│   ├── check_response(request_id) → response | None
│   ├── escalate_to_feishu(request)
│   ├── archive_request(request_id)
│   ├── get_pending_requests() → list
│   └── cleanup_old_requests()
│
├── RequestBuilder
│   ├── build_bastion_disconnect(error_data)
│   ├── build_dependency_request(dep_data)
│   ├── build_gpu_occupied(gpu_data)
│   ├── build_cpu_overload(cpu_data)
│   └── _generate_request_id(request_type)
│
├── ResponseHandler
│   ├── execute_next_step(response, scheduler)
│   ├── handle_timeout(request, scheduler)
│   └── get_fallback_action(request_type)
│
└── CLI Interface
    ├── --status: Show current communication state
    ├── --pending: Show pending requests
    ├── --test: Test communication
    └── --cleanup: Clean old files
```

---

## File Structure

```
D:\workspace\apmm\
├── .agent_comm/
│   ├── requests/              # Runner → Supervisor
│   │   ├── bastion_disconnect_001.json
│   │   ├── dependency_request_002.json
│   │   ├── gpu_occupied_003.json
│   │   └── cpu_overload_004.json
│   ├── responses/             # Supervisor → Runner
│   │   ├── bastion_disconnect_001.json
│   │   ├── dependency_request_002.json
│   │   ├── gpu_occupied_003.json
│   │   └── cpu_overload_004.json
│   ├── processed/             # Archived processed requests
│   └── status.json            # Current communication state
│
├── tasks/ut/scripts/
│   ├── agent_comm.py          # Communication module
│   ├── feishu_notifier.py     # Feishu escalation
│   └── test_scheduler.py      # Integration
```

---

## Request Format

### Bastion Disconnect Request

```json
{
  "request_id": "bastion_disconnect_001",
  "request_type": "bastion_disconnect",
  "priority": "P0",
  "from_agent": "Unit Test Runner Agent",
  "to_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:30:00",
  "data": {
    "error_message": "agent.py ping failed 3 consecutive times",
    "consecutive_failures": 3,
    "last_successful_ping": "2026-06-05T14:25:00",
    "current_test_status": "paused",
    "affected_tests": 6500
  },
  "suggestion": "等待 Supervisor 恢复连接或人工检查 bastion",
  "status": "pending"
}
```

### Dependency Request

```json
{
  "request_id": "dependency_request_002",
  "request_type": "dependency_request",
  "priority": "P1",
  "from_agent": "Unit Test Runner Agent",
  "to_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:35:00",
  "data": {
    "dependency_type": "hf_model",
    "dependency_name": "meta-llama/Llama-3.2-1B-Instruct",
    "required_for_tests": [
      "tests/models/test_llama.py",
      "tests/entrypoints/test_llm.py"
    ],
    "affected_tests": 1500,
    "download_size": "~1.5GB",
    "hf_mirror_available": true
  },
  "suggestion": "联络 Download Agent 下载模型到 hf_hub/",
  "status": "pending"
}
```

### GPU Occupied Request

```json
{
  "request_id": "gpu_occupied_003",
  "request_type": "gpu_occupied",
  "priority": "P0",
  "from_agent": "Unit Test Runner Agent",
  "to_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:40:00",
  "data": {
    "gpu_status": {
      "GPU0": {"memory_used": "131GB", "memory_total": "140GB", "process": "pid_12345"},
      "GPU1": {"memory_used": "131GB", "memory_total": "140GB", "process": "pid_12345"},
      "GPU2": {"memory_used": "130GB", "memory_total": "140GB", "process": "pid_12346"},
      "GPU3": {"memory_used": "130GB", "memory_total": "140GB", "process": "pid_12346"},
      "GPU4": {"memory_used": "5GB", "memory_total": "140GB", "process": "idle"},
      "GPU5": {"memory_used": "5GB", "memory_total": "140GB", "process": "idle"},
      "GPU6": {"memory_used": "130GB", "memory_total": "140GB", "process": "pid_12347"},
      "GPU7": {"memory_used": "130GB", "memory_total": "140GB", "process": "pid_12347"}
    },
    "idle_gpus": ["4", "5"],
    "occupying_processes": ["pid_12345", "pid_12346", "pid_12347"],
    "affected_tests": 8000
  },
  "suggestion": "协调其他进程释放 GPU 或使用空闲 GPU 4-5",
  "status": "pending"
}
```

### CPU Overload Request

```json
{
  "request_id": "cpu_overload_004",
  "request_type": "cpu_overload",
  "priority": "P1",
  "from_agent": "Unit Test Runner Agent",
  "to_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:45:00",
  "data": {
    "cpu_usage": "92%",
    "load_average": [8.5, 7.8, 6.2],
    "occupying_processes": [
      {"pid": "12345", "name": "other_process", "cpu": "45%"},
      {"pid": "12346", "name": "another_process", "cpu": "30%"}
    ],
    "affected_tests": 5000,
    "current_workers": 3
  },
  "suggestion": "协调其他进程或建议将 workers 降到 1",
  "status": "pending"
}
```

---

## Response Format

### Success Response

```json
{
  "request_id": "bastion_disconnect_001",
  "status": "processed",
  "from_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:32:00",
  "action": {
    "type": "reconnect_bastion",
    "description": "已重新建立 bastion SSH 连接",
    "performed_by": "supervisor_agent"
  },
  "result": "success",
  "next_step": {
    "action": "resume_test_execution",
    "description": "Runner Agent 可恢复测试执行"
  }
}
```

### Processing Response

```json
{
  "request_id": "dependency_request_002",
  "status": "processing",
  "from_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:37:00",
  "action": {
    "type": "contact_download_agent",
    "description": "已联络 Download Agent 下载模型",
    "performed_by": "download_agent",
    "estimated_time": "30分钟"
  },
  "result": "in_progress",
  "next_step": {
    "action": "pause_and_wait",
    "description": "Runner Agent 暂停相关测试，等待下载完成",
    "wait_timeout": 1800
  }
}
```

### Cannot Process Response

```json
{
  "request_id": "cpu_overload_004",
  "status": "cannot_process",
  "from_agent": "Supervisor Agent",
  "timestamp": "2026-06-05T14:47:00",
  "action": {
    "type": "no_action",
    "description": "其他进程优先级更高，无法协调"
  },
  "result": "failed",
  "reason": "other_processes_priority_higher",
  "next_step": {
    "action": "reduce_parallelism",
    "description": "Runner Agent 自行降低并行度",
    "suggestion": {
      "reduce_workers_to": 1,
      "description": "建议将 workers 从 3 降到 1"
    }
  }
}
```

---

## status.json Format

```json
{
  "last_update": "2026-06-05T14:45:00",
  "pending_requests": ["dependency_request_002"],
  "processing_requests": [],
  "processed_requests": ["bastion_disconnect_001", "gpu_occupied_003"],
  "escalated_requests": [],
  "agents_status": {
    "Unit Test Runner Agent": "running",
    "Supervisor Agent": "active",
    "Download Agent": "processing_dependency_request_002"
  }
}
```

---

## Integration Points

### test_scheduler.py Integration

```python
from agent_comm import AgentCommunicator, CommConfig, RequestType

class Scheduler:
    def __init__(self, config: SchedulerConfig):
        # Agent communication init
        comm_config = CommConfig(
            comm_dir=work_dir.parent.parent / ".agent_comm"
        )
        self.agent_comm = AgentCommunicator(
            config=comm_config,
            feishu_notifier=self.feishu_notifier
        )
    
    def check_agent_health(self) -> bool:
        ping_success = self._ping_agent()
        if not ping_success:
            self.bastion_fail_count += 1
            if self.bastion_fail_count >= 3:
                request = self.agent_comm.send_request(
                    RequestType.BASTION_DISCONNECT,
                    {"consecutive_failures": self.bastion_fail_count}
                )
                response = self.agent_comm.wait_response(request["request_id"])
                if response:
                    self._execute_next_step(response)
                else:
                    self.pause_execution()
    
    def check_gpu_availability(self) -> bool:
        gpu_status = self._get_gpu_status()
        if len(gpu_status["idle_gpus"]) < 2:
            request = self.agent_comm.send_request(
                RequestType.GPU_OCCUPIED,
                {"gpu_status": gpu_status}
            )
            response = self.agent_comm.wait_response(request["request_id"])
            if response and response["result"] == "success":
                self._reassign_gpus(response["action"]["released_gpus"])
            else:
                self.config.parallel_count = 1
```

---

## ResponseHandler Logic

```python
class ResponseHandler:
    def execute_next_step(self, response: dict, scheduler: Scheduler):
        next_step = response.get("next_step", {})
        action = next_step.get("action")
        
        match action:
            case "resume_test_execution":
                scheduler.resume_execution()
            case "resume_with_gpu_4_5":
                scheduler._reassign_gpus(next_step.get("gpus"))
                scheduler.resume_execution()
            case "pause_and_wait":
                scheduler.pause_execution()
                scheduler._wait_for_dependency(next_step.get("wait_timeout"))
            case "reduce_parallelism":
                scheduler.config.parallel_count = next_step.get(
                    "suggestion", {}).get("reduce_workers_to", 1)
                scheduler._restart_workers()
            case "skip_tests":
                scheduler._skip_tests_by_dependency(
                    next_step.get("dependency_name"))
    
    def handle_timeout(self, request: dict, scheduler: Scheduler):
        request_type = request["request_type"]
        
        # Fallback actions
        match request_type:
            case "bastion_disconnect":
                scheduler.pause_execution()
            case "gpu_occupied":
                scheduler.config.parallel_count = 1
            case "dependency_request":
                scheduler._skip_dependency_tests(
                    request["data"]["dependency_name"])
            case "cpu_overload":
                scheduler.config.parallel_count = 1
        
        # Feishu escalation
        if scheduler.feishu_notifier:
            scheduler.feishu_notifier.notify_supervisor_timeout({
                "request": request,
                "fallback_action": self.get_fallback_action(request_type)
            })
```

---

## Escalation Mechanism

### Feishu Escalation Card

```
┌─────────────────────────────────────┐
│ 🚨 Supervisor 请求超时              │
├─────────────────────────────────────┤
│                                      │
│ **请求类型**: GPU 占用               │
│ **请求ID**: gpu_occupied_003         │
│ **发送时间**: 14:40:00               │
│ **等待时长**: 60s                    │
│                                      │
│ **问题描述**:                        │
│ 所有 GPU 被占用，仅 GPU 4-5 空闲     │
│ 影响测试: 8000                       │
│                                      │
│ **已采取降级措施**:                  │
│ 降低并行度至 1 worker                │
│                                      │
│ **需要人工介入**:                    │
│ 请检查 GPU 占用进程并协调释放        │
│                                      │
├─────────────────────────────────────┤
│ 🕐 2026-06-05 14:42:00               │
│ 🤖 Unit Test Runner Agent            │
└─────────────────────────────────────┘
```

### feishu_notifier.py New Methods

```python
def notify_supervisor_timeout(self, timeout_data: dict):
    """Escalation when Supervisor doesn't respond"""
    self.send_card(
        title="🚨 Supervisor 请求超时",
        elements=[
            {"tag": "div", "text": {"tag": "lark_md",
                "content": f"**请求类型**: {timeout_data['request']['request_type']}\n"
                           f"**请求ID**: {timeout_data['request']['request_id']}\n"
                           f"**等待时长**: 已超时"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md",
                "content": f"**问题描述**:\n{timeout_data['request']['suggestion']}\n\n"
                           f"**已采取降级措施**:\n{timeout_data['fallback_action']}"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md",
                "content": "**需要人工介入**: 请检查并处理上述问题"}},
            {"tag": "hr"},
            {"tag": "note", "elements": [
                {"tag": "plain_text", "content": f"🕐 {datetime.now()}"},
                {"tag": "plain_text", "content": "🤖 Unit Test Runner Agent"}
            ]}
        ]
    )
```

---

## Fallback Actions

| Request Type | Timeout | Fallback Action |
|--------------|:-------:|-----------------|
| bastion_disconnect | 60s | Pause execution, retry every 30s |
| gpu_occupied | 60s | Reduce workers to 1 |
| dependency_request | 120s | Skip related tests |
| cpu_overload | 120s | Reduce workers to 1 |

---

## File Cleanup

```python
def cleanup_old_requests(self, max_age_hours: int = 24):
    """Archive processed requests older than 24 hours"""
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    
    for request_file in self.request_dir.glob("*.json"):
        request = json.loads(request_file.read_text())
        if request["status"] == "processed":
            request_time = datetime.fromisoformat(request["timestamp"])
            if request_time < cutoff_time:
                dest = self.processed_dir / request_file.name
                request_file.rename(dest)
```

---

## CLI Commands

```bash
# Show communication status
python agent_comm.py --status

# Show pending requests
python agent_comm.py --pending

# Test communication
python agent_comm.py --test

# Cleanup old files
python agent_comm.py --cleanup
```

---

## Success Criteria

| Criteria | Target |
|----------|:------:|
| Request delivery | < 1s write time |
| Response detection | < poll_interval (5s) |
| Timeout handling | Autonomous fallback |
| Feishu escalation | Within timeout + 5s |
| No test interruption | Tests continue with fallback |

---

*Created: 2026-06-05*
*Status: Draft - Pending Approval*