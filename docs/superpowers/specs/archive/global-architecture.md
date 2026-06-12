# 全局架构设计

> **⚠️ DEPRECATED - 此文档已过时**
> 
> **最新方案**: [../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)
> 
> 此文档基于原四Agent架构设计，新架构已简化为双Agent（Supervisor + Runner）。

---

## 原设计（已废弃）

> **Agent协同系统 - 通信协议与状态管理**
> **创建日期: 2026-06-06**
> **版本: 1.0.0**

---

## 目录结构

### Spec文档目录

```
docs/superpowers/specs/agents/
├── README.md                          # 总览
├── global-architecture.md             # 本文件
│
├── supervisor-agent/
│   ├── README.md                      # Supervisor职责
│   ├── message-routing.md             # 消息路由逻辑
│   └── feishu-notification.md         # 飞书通知模板
│
├── unit-test-runner-agent/
│   ├── README.md                      # Runner职责
│   ├── test-automation-design.md      # 测试自动化架构
│   ├── test-execution-plan.md         # 执行策略
│   ├── agent-communication.md         # Runner通信协议
│   └── progress-tracking.md           # 进度追踪
│
├── environment-agent/
│   ├── README.md                      # Environment职责
│   ├── gpu-monitoring.md              # GPU监控
│   ├── container-management.md        # 容器管理
│   ├── dependency-handling.md         # 依赖处理
│   └── conflict-resolution.md         # 冲突解决
│
└── bastion-agent/
    ├── README.md                      # Bastion职责
    ├── connection-monitoring.md       # 连接监控
    ├── disconnect-recovery.md         # 断连恢复
    └── otp-handling.md                # OTP处理
```

### 状态文件目录

```
D:\workspace\apmm\.agents/
├── config.json              # 全局配置
├── global_state.json        # 全局状态汇总
├── feishu_config.json       # 飞书配置（敏感，不入git）
│
├── runner/
│   ├── status.json          # Runner状态
│   ├── messages.jsonl       # Runner发送的消息
│   └── inbox.jsonl          # Supervisor发给Runner的消息
│
├── environment/
│   ├── status.json          # Environment状态
│   ├── messages.jsonl       # Environment发送的消息
│   └── inbox.jsonl          # Supervisor发给Environment的消息
│
├── bastion/
│   ├── status.json          # Bastion状态
│   ├── messages.jsonl       # Bastion发送的消息
│   └── inbox.jsonl          # Supervisor发给Bastion的消息
│
├── supervisor/
│   ├── status.json          # Supervisor状态
│   └── heartbeat.json       # 心跳时间戳
│
└── archive/
    ├── processed_messages.jsonl    # 已处理消息归档
    └── resolved_issues.jsonl       # 已解决问题归档
```

---

## config.json 格式

```json
{
  "version": "1.0.0",
  "agents": {
    "supervisor": {
      "type": "hermes",
      "status_file": ".agents/supervisor/status.json",
      "heartbeat_file": ".agents/supervisor/heartbeat.json",
      "spec_file": "docs/superpowers/specs/agents/supervisor-agent/README.md",
      "description": "协调Agent，转发消息，飞书通知"
    },
    "unit-test-runner": {
      "type": "claude-code",
      "status_file": ".agents/runner/status.json",
      "messages_file": ".agents/runner/messages.jsonl",
      "inbox_file": ".agents/runner/inbox.jsonl",
      "spec_file": "docs/superpowers/specs/agents/unit-test-runner-agent/README.md",
      "description": "执行测试，修复失败，统计进度"
    },
    "environment": {
      "type": "claude-code",
      "status_file": ".agents/environment/status.json",
      "messages_file": ".agents/environment/messages.jsonl",
      "inbox_file": ".agents/environment/inbox.jsonl",
      "spec_file": "docs/superpowers/specs/agents/environment-agent/README.md",
      "description": "监控GPU/容器，下载依赖，处理冲突"
    },
    "bastion": {
      "type": "claude-code",
      "status_file": ".agents/bastion/status.json",
      "messages_file": ".agents/bastion/messages.jsonl",
      "inbox_file": ".agents/bastion/inbox.jsonl",
      "spec_file": "docs/superpowers/specs/agents/bastion-agent/README.md",
      "description": "监控Bastion连接，处理断连，OTP验证"
    }
  },
  "global_state_file": ".agents/global_state.json",
  "communication_dir": ".agents/",
  "spec_dir": "docs/superpowers/specs/agents/",
  "feishu_config": ".agents/feishu_config.json"
}
```

---

## status.json 格式（各Agent通用）

```json
{
  "agent_id": "unit-test-runner",
  "agent_type": "claude-code",
  "status": "running",
  "started_at": "2026-06-06T10:00:00",
  "last_update": "2026-06-06T10:30:00",
  "current_task": {
    "description": "执行Phase 1 Round 1测试",
    "phase": 1,
    "round": 1,
    "progress": "4200/7740"
  },
  "statistics": {
    "tests_completed": 4200,
    "tests_passed": 3800,
    "tests_failed": 300,
    "tests_error": 120
  },
  "issues": [],
  "config_paths": {
    "status_file": ".agents/runner/status.json",
    "messages_file": ".agents/runner/messages.jsonl",
    "inbox_file": ".agents/runner/inbox.jsonl",
    "spec_file": "docs/superpowers/specs/agents/unit-test-runner-agent/README.md"
  }
}
```

**status字段值定义：**

| 状态 | 含义 | 触发场景 |
|------|------|----------|
| `starting` | 正在初始化 | Agent刚启动 |
| `running` | 正常执行任务 | 主循环运行中 |
| `paused` | 等待外部响应 | 等待依赖/用户指令 |
| `waiting` | 等待资源 | 等待GPU空闲 |
| `error` | 需要人工介入 | 无法自动恢复 |
| `stopped` | 用户手动停止 | 收到stop指令 |
| `completed` | 任务完成 | 所有测试完成 |

---

## messages.jsonl 格式

每行一条JSON消息，追加写入：

```json
{"type": "agent_started", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T10:00:00", "data": {"message": "Unit Test Runner Agent启动成功"}}
{"type": "progress_milestone", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T10:30:00", "priority": "P2", "data": {"completed": 100, "total": 7740, "phase": 1, "round": 1}}
{"type": "bastion_disconnect", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T10:35:00", "priority": "P0", "data": {"consecutive_failures": 3, "last_ping": "2026-06-06T10:32:00"}}
{"type": "dependency_request", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T10:40:00", "priority": "P1", "data": {"dependency_type": "hf_model", "name": "meta-llama/Llama-3.2-1B-Instruct", "affected_tests": 1500}}
{"type": "gpu_occupied", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T10:45:00", "priority": "P0", "data": {"idle_gpus": ["4", "5"], "occupying_pids": ["12345", "12346"]}}
{"type": "phase_complete", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T12:00:00", "priority": "P1", "data": {"phase": 1, "round": 1, "stats": {"passed": 6880, "failed": 580, "error": 420}}}
{"type": "all_complete", "agent_id": "unit-test-runner", "timestamp": "2026-06-06T18:00:00", "priority": "P1", "data": {"total_tests": 31947, "duration_hours": 22.5}}
```

---

## inbox.jsonl 格式

Supervisor发送给Agent的消息：

```json
{"type": "response", "request_id": "dependency_request_001", "timestamp": "2026-06-06T10:42:00", "from": "supervisor", "action": "download_started", "data": {"estimated_time": "30min"}}
{"type": "response", "request_id": "gpu_occupied_002", "timestamp": "2026-06-06T10:47:00", "from": "supervisor", "action": "use_idle_gpus", "data": {"gpus": ["4", "5"]}}
{"type": "command", "timestamp": "2026-06-06T11:00:00", "from": "supervisor", "action": "pause_execution", "data": {"reason": "用户请求暂停"}}
{"type": "otp_code", "timestamp": "2026-06-06T11:05:00", "from": "supervisor", "code": "123456", "data": {"source": "user_via_feishu"}}
```

---

## 消息类型定义

### Unit Test Runner → Supervisor

| 类型 | 优先级 | 含义 | Supervisor处理 |
|------|:------:|------|----------------|
| `agent_started` | P2 | Agent启动 | 发飞书通知 |
| `agent_stopped` | P2 | Agent停止 | 发飞书通知 |
| `progress_milestone` | P2 | 每100测试 | 发飞书卡片 |
| `bastion_disconnect` | P0 | SSH断连 | 联系Bastion Agent |
| `dependency_request` | P1 | 依赖缺失 | 联系Environment Agent |
| `gpu_occupied` | P0 | GPU占用 | 联系Environment Agent |
| `cpu_overload` | P1 | CPU过载 | 联系Environment Agent |
| `phase_complete` | P1 | 阶段完成 | 发飞书卡片 |
| `all_complete` | P1 | 全部完成 | 发飞书卡片 |
| `fallback_triggered` | P1 | 执行fallback | 发飞书告警 |

### Environment Agent → Supervisor

| 类型 | 优先级 | 含义 | Supervisor处理 |
|------|:------:|------|----------------|
| `agent_started` | P2 | Agent启动 | 发飞书通知 |
| `gpu_intrusion` | P0 | GPU被抢占 | 发飞书告警（需人工） |
| `cpu_intrusion` | P1 | CPU被占用 | 发飞书告警 |
| `container_error` | P0 | 容器异常 | 发飞书告警（需人工） |
| `dependency_ready` | P2 | 下载完成 | 通知Runner继续 |
| `dependency_failed` | P0 | 下载失败 | 发飞书告警（需人工） |
| `environment_status` | P2 | 定时汇报 | 更新global_state |

### Bastion Agent → Supervisor

| 类型 | 优先级 | 含义 | Supervisor处理 |
|------|:------:|------|----------------|
| `agent_started` | P2 | Agent启动 | 发飞书通知 |
| `bastion_unstable` | P1 | 连接不稳定 | 发飞书警告 |
| `bastion_disconnect` | P0 | 完全断连 | 发飞书告警 |
| `bastion_recovered` | P2 | 恢复成功 | 发飞书通知，通知Runner |
| `bastion_recovery_failed` | P0 | 恢复失败 | 发飞书OTP请求告警 |
| `otp_required` | P0 | 需要OTP | 发飞书OTP请求告警 |
| `bastion_status` | P2 | 定时汇报 | 更新global_state |

---

## global_state.json 格式

```json
{
  "last_update": "2026-06-06T10:45:00",
  "agents": {
    "supervisor": {
      "status": "running",
      "last_heartbeat": "2026-06-06T10:45:00",
      "uptime_seconds": 2700
    },
    "unit-test-runner": {
      "status": "running",
      "last_update": "2026-06-06T10:44:00",
      "current_task": "Phase 1 Round 1",
      "progress": "4200/7740",
      "connection_health": "healthy"
    },
    "environment": {
      "status": "running",
      "last_update": "2026-06-06T10:43:00",
      "current_task": "监控GPU状态",
      "gpu_status": {
        "idle": ["4", "5"],
        "occupied": ["0", "1", "2", "3", "6", "7"]
      },
      "connection_health": "healthy"
    },
    "bastion": {
      "status": "running",
      "last_update": "2026-06-06T10:45:00",
      "current_task": "监控Bastion连接",
      "bastion_status": {
        "t_h20": "connected",
        "t_ascend": "connected"
      },
      "connection_health": "healthy",
      "waiting_for_otp": false
    }
  },
  "test_progress": {
    "phase": 1,
    "round": 1,
    "total_tests": 7740,
    "completed": 4200,
    "passed": 3800,
    "failed": 300,
    "error": 120,
    "estimated_remaining": "1.2 hours"
  },
  "pending_requests": [
    {
      "request_id": "dependency_request_001",
      "type": "dependency_request",
      "from": "unit-test-runner",
      "status": "processing",
      "assigned_to": "environment",
      "created_at": "2026-06-06T10:40:00"
    }
  ],
  "recent_alerts": [
    {
      "type": "gpu_intrusion",
      "timestamp": "2026-06-06T10:45:00",
      "resolved": false,
      "requires_human": true
    }
  ],
  "system_health": {
    "all_agents_connected": true,
    "bastion_connected": true,
    "gpu_available": false,
    "critical_issues": 1
  }
}
```

---

## Agent失联检测

### 检测机制

```
检测条件:
├── Agent的status.json last_update 超过60秒未更新
│   或
└── Agent的messages.jsonl 超过60秒无新消息

失联等级:
├── Level 1 (可疑): 超过60秒 → 发飞书警告
├── Level 2 (确认失联): 超过120秒 → 发飞书告警，尝试联系
└── Level 3 (严重失联): 超过180秒 → 发飞书紧急告警，提示用户检查终端
```

---

## 飞书用户指令协议

### 指令格式

用户在飞书群发送消息，Supervisor识别并执行：

| 指令类别 | 指令示例 | Supervisor动作 |
|----------|----------|----------------|
| **状态查询** | `状态`、`进度`、`Runner状态` | 返回对应状态卡片 |
| **控制指令** | `暂停Runner`、`继续Runner` | 转发指令给对应Agent |
| **OTP验证** | `OTP 123456`、`验证码 123456` | 转发给Bastion Agent |
| **下载请求** | `下载模型 meta-llama/xxx` | 转发给Environment Agent |

### OTP特殊处理

```
OTP流程:
├── 用户发送: "OTP 123456"
├── Supervisor解析: {"type": "otp_code", "code": "123456"}
├── 写入bastion/inbox.jsonl
├── 发飞书确认: "OTP已转发给Bastion Agent"
└── Bastion Agent收到后执行SSH重启
```

---

*创建日期: 2026-06-06*
*状态: Draft - Pending Review*