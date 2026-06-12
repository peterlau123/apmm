# Unit Test Runner Agent 设计

> **Agent协同系统 - Unit Test Runner Agent (Claude Code)**
> **职责: 测试执行、失败修复、进度统计、问题汇报**
> **创建日期: 2026-06-06**

---

## Agent信息

| 属性 | 值 |
|------|-----|
| Agent ID | `unit-test-runner` |
| Agent类型 | Claude Code CLI |
| 终端窗口 | #2 |
| 状态文件 | `.agents/runner/status.json` |
| 消息文件 | `.agents/runner/messages.jsonl` |
| 接收文件 | `.agents/runner/inbox.jsonl` |
| Spec文件 | `docs/superpowers/specs/agents/unit-test-executor-agent/README.md` |

---

## 核心职责

```
┌─────────────────────────────────────────────────────────────────┐
│                    Unit Test Runner Agent职责                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ✅ 测试执行                                                     │
│  ├── 按Phase/Round策略执行pytest                                 │
│  ├── 并行执行（3 workers，GPU 0-1/2-3/4-5）                      │
│  ├── 后台执行（nohup pytest）                                    │
│  ├── 超时处理（120s model-free, 300s model-dependent）           │
│  └── 断连恢复后继续执行                                          │
│                                                                  │
│  ✅ 失败修复                                                     │
│  ├── 分析失败原因（C/E/D/P/M/S分类）                              │
│  ├── 尝试修复简单问题                                            │
│  ├── 连续错误阈值处理（5次）                                      │
│  └── 记录到issues.json                                           │
│                                                                  │
│  ✅ 进度统计                                                     │
│  ├── 更新test_manifest.json                                     │
│  ├── 更新execution_state.json                                    │
│  ├── 更新status.json                                             │
│  └── 每100测试汇报里程碑                                          │
│                                                                  │
│  ✅ 问题汇报                                                     │
│  ├── bastion_disconnect: SSH ping失败3次                         │
│  ├── dependency_request: ImportError/model缺失                   │
│  ├── gpu_occupied: GPU被占用                                     │
│  ├── cpu_overload: CPU超过85%                                    │
│  └── phase_complete/all_complete                                 │
│                                                                  │
│  ✅ 自主fallback                                                 │
│  ├── bastion断连 → 暂停执行，每30秒重试                           │
│  ├── GPU占用 → 降级为1 worker                                    │
│  ├── 依赖缺失 → 跳过相关测试                                      │
│  ├── CPU过载 → 降级为1 worker                                    │
│                                                                  │
│  ❌ 不负责                                                       │
│  ├── 不下载依赖/模型（向Supervisor请求）                          │
│  ├── 不维护容器/环境                                             │
│  ├── 不处理Bastion连接（只检测并汇报）                            │
│  ├── 不发飞书通知（由Supervisor转发）                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 启动方式

Runner由Supervisor自动启动，无需手动干预：

```
Supervisor启动流程:
├── supervisor_loop.py 启动
├── 检查Runner状态文件 (.agents/unit-test-runner/status.json)
├── Runner未运行 → 调用 start_runner_agent.py start
├── 启动Claude Code CLI进程
├── Runner已运行 → 跳过启动
└── Runner PID记录到 status.json
```

### 启动脚本

`start_runner_agent.py`负责启动Runner：

```bash
# Supervisor调用（自动）
python skills/ut/supervisor/scripts/start_runner_agent.py start

# 手动干预（可选）
python skills/ut/supervisor/scripts/start_runner_agent.py status
python skills/ut/supervisor/scripts/start_runner_agent.py stop
```

### 启动流程

```
start_runner_agent.py 启动时:
├── 检查Runner心跳文件
├── 心跳超时 (>30秒) → 认为未运行
├── 初始化 status.json = {"status": "starting"}
├── 启动Claude Code CLI进程
│   ├── subprocess.Popen([claude, --workdir, ...])
│   ├── 发送启动指令到stdin
│   └── 记录PID
├── 更新 status.json = {"status": "running", "pid": ...}
├── 等待验证启动成功
└── 返回结果
```

### Runner运行模式

Runner作为Claude Code CLI进程运行：

```
Runner进程:
├── Claude Code CLI主进程
├── 自动加载 unit-test-runner skill
├── 执行测试（通过SSH远程）
├── 更新状态文件
│   ├── status.json (进度、状态)
│   ├── heartbeat.json (心跳)
│   └── messages.jsonl (汇报消息)
└── 接收Supervisor指令（inbox.jsonl）
```

---

## 主循环逻辑

### 测试执行循环

```
┌─────────────────────────────────────────────────────────────────┐
│                    Runner主循环                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  每批次执行:                                                     │
│  ├── 1. 检查inbox.jsonl是否有新指令                              │
│  │     ├── pause指令 → 暂停执行                                  │
│  │     ├── resume指令 → 继续执行                                 │
│  │     ├── response → 处理Supervisor响应                         │
│  │                                                              │
│  ├── 2. 检查环境状态                                             │
│  │     ├── Bastion健康检查 (ping)                                │
│  │     ├── GPU可用性检查                                         │
│  │     ├── CPU负载检查                                           │
│  │                                                              │
│  ├── 3. 发现问题 → 汇报给Supervisor                              │
│  │     ├── bastion_disconnect                                   │
│  │     ├── gpu_occupied                                         │
│  │     ├── dependency_request                                   │
│  │                                                              │
│  ├── 4. 执行一批测试 (10个测试/批次)                              │
│  │     ├── 并行执行 (3 workers)                                  │
│  │     ├── 后台运行 (nohup)                                      │
│  │     ├── 监控日志                                              │
│  │                                                              │
│  ├── 5. 处理结果                                                 │
│  │     ├── 分析失败原因                                          │
│  │     ├── 更新manifest                                          │
│  │     ├── 连续错误检测                                          │
│  │                                                              │
│  ├── 6. 更新状态                                                 │
│  │     ├── 更新status.json                                       │
│  │     ├── 每100测试发送progress_milestone                       │
│  │                                                              │
│  └── 7. Supervisor不响应时执行fallback                           │
│     ├── 等待超时 → 自主处理                                      │
│     ├── 记录fallback_triggered                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 汇报给Supervisor的场景

| 消息类型 | 触发条件 | 优先级 | 数据内容 |
|----------|----------|:------:|----------|
| `agent_started` | Agent启动完成 | P2 | 启动时间、配置路径 |
| `progress_milestone` | 每100测试完成 | P2 | completed, total, phase, round |
| `bastion_disconnect` | SSH ping失败3次 | P0 | consecutive_failures, last_ping |
| `dependency_request` | ImportError/model缺失 | P1 | dependency_type, name, affected_tests |
| `gpu_occupied` | GPU被其他进程占用 | P0 | idle_gpus, occupying_pids |
| `cpu_overload` | CPU超过85% | P1 | cpu_usage, occupying_processes |
| `phase_complete` | Phase/Round完成 | P1 | phase, round, stats |
| `all_complete` | 所有测试完成 | P1 | total_tests, duration_hours |
| `fallback_triggered` | 执行fallback策略 | P1 | fallback_type, reason |

---

## 自主Fallback策略

| 问题类型 | Supervisor响应超时 | Fallback动作 |
|----------|--------------------|--------------|
| `bastion_disconnect` | 60秒 | 暂停执行，每30秒重试ping |
| `gpu_occupied` | 60秒 | 降级为1 worker，使用空闲GPU |
| `dependency_request` | 120秒 | 跳过依赖相关测试，继续其他 |
| `cpu_overload` | 120秒 | 降级为1 worker |

### Fallback流程

```
发现问题 → 发送消息给Supervisor → 等待响应
    │
    ├── Supervisor响应 → 执行响应指令
    │
    └── 等待超时 → 执行fallback
        ├── 更新status.json: {"status": "fallback"}
        ├── 执行fallback动作
        ├── 发送fallback_triggered消息
        └── 继续执行（降级模式）
```

---

## inbox消息处理

| 收到消息类型 | 动作 |
|--------------|------|
| `command: pause` | 暂停执行，更新status.json |
| `command: resume` | 继续执行 |
| `command: stop` | 停止执行，清理进程 |
| `response: download_started` | 等待依赖下载，暂停相关测试 |
| `response: download_ready` | 继续执行相关测试 |
| `response: use_idle_gpus` | 重新分配GPU |
| `response: skip_dependency` | 跳过依赖相关测试 |

---

## 用户指令

用户通过Supervisor发送指令（飞书群或Hermes Session）：

| 指令 | 动作 |
|------|------|
| `otp 123456` | 转发OTP给Bastion |
| `check status` | 发送status_request |
| `pause runner` | 暂停Runner执行 |
| `resume runner` | 继续Runner执行 |
| `stop runner` | 停止Runner进程 |

Runner收到指令后：
- 执行相应动作
- 更新status.json
- 通过messages.jsonl汇报结果

---

## 相关文档

- [test-automation-design.md](./test-automation-design.md) - 测试自动化架构详细设计
- [test-execution-plan.md](./test-execution-plan.md) - 多轮执行策略
- [agent-communication.md](./agent-communication.md) - Runner通信协议
- [progress-tracking.md](./progress-tracking.md) - 进度追踪机制

---

*创建日期: 2026-06-06*
*更新日期: 2026-06-08*
*状态: 已实现 - Supervisor自动启动Runner*