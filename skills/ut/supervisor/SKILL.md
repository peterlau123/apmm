---
name: supervisor
description: Supervisor Agent，负责协调各Agent、消息路由、飞书通知、状态监控
version: 1.0.0
when_to_use: 作为Supervisor Agent运行，协调Runner/Environment/Bastion Agent工作
---

# Supervisor Agent Skill

## Agent身份识别

启动时自动识别：
- 在Hermes Session中执行Supervisor职责
- 读取 `.agents/config.json` 获取文件路径
- 读取本Skill文档了解职责边界

## 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "supervisor"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 docs/superpowers/specs/agents/supervisor-agent/README.md
├── 了解职责边界
├── 了解消息路由规则

Step 3: 初始化状态
├── 写入 status.json = {"status": "starting"}
├── 清空 inbox.jsonl
├── 初始化 last_poll_time.json

Step 4: 发送启动通知
├── 写入 messages.jsonl:
│   {"type": "agent_started", "agent_id": "supervisor", ...}
├── 发送飞书通知: Supervisor Agent已启动

Step 5: 启动后台进程 ← 自动执行
├── 执行: python scripts/supervisor_loop.py start
├── 自动启动 supervisor_loop.py（后台）
│   ├── 检查loop.lock → 已运行则跳过
│   ├── 未运行 → subprocess.Popen启动
│   └── start_new_session=True → 完全分离
├── 验证启动成功（等待2秒检查lock文件）
└── 失败时打印错误，继续执行

Step 6: 进入监控循环
├── 更新 status.json = {"status": "monitoring"}
├── 开始循环监控（每5秒）
│   ├── 消息轮询（每10秒）
│   ├── 状态检查（每5秒）
│   ├── 飞书监听（后台）
│   └── 心跳更新（每5秒）
```

## 监控职责

### 消息轮询（每10秒）

执行流程：

1. **读取各Agent消息队列**
   ```bash
   python scripts/supervisor_message_poll.py
   ```
   输出JSON:
   ```json
   {"processed": 3, "messages": ["bastion_disconnect", ...]}
   ```

2. **路由消息**
   - bastion_disconnect → 发送飞书OTP请求
   - gpu_occupied → 转发给Runner
   - dependency_request → 转发给Environment
   - progress_milestone → 发送飞书进度通知
   - phase_complete → 发送飞书完成通知

3. **处理飞书回复**
   - 用户回复OTP → 转发给Bastion inbox
   - 用户回复指令 → 转发给对应Agent

### 状态检查（每5秒）

执行流程：

1. **检查各Agent心跳**
   ```bash
   python scripts/supervisor_status_check.py
   ```
   输出JSON:
   ```json
   {"agents": {"runner": {"status": "running", "heartbeat_age": 2.3}}}
   ```

2. **检测失联Agent**
   - 心跳超过30秒 → 发送agent_timeout消息
   - 飞书通知用户Agent失联

3. **更新Supervisor心跳**
   ```bash
   python scripts/update_heartbeat.py
   ```

### 飞书监听（后台）

执行流程：

1. **监听飞书群消息**
   ```bash
   python scripts/supervisor_feishu_listen.py
   ```

2. **解析用户指令**
   - `otp 123456` → 转发OTP给Bastion
   - `pause runner` → 发送pause指令给Runner
   - `check status` → 发送status_request给所有Agent

3. **响应格式**
   ```json
   {"type": "feishu_command", "command": "otp", "value": "123456"}
   ```

## 汇报规则

### 飞书通知场景

| 类型 | 优先级 | 触发条件 | 飞书消息 |
|------|:------:|----------|----------|
| bastion_disconnect | P0 | SSH断连 | 🔴 SSH连接断开，需要启动daemon和OTP |
| otp_required | P0 | Bastion请求OTP | 🔴 需要OTP验证码启动SSH daemon |
| runner_stalled | P0 | Runner心跳超时 | 🔴 Runner停滞，需要检查 |
| progress_milestone | P2 | 每100测试 | 📊 测试进度：X/Y |
| phase_complete | P1 | Phase完成 | ✅ Phase X完成 |
| all_complete | P1 | 全部完成 | ✅ 所有测试完成 |
| agent_started | P2 | Agent启动 | 📢 Agent X已启动 |

### 消息模板

使用 `templates/` 目录下的JSON模板。

## inbox处理

| 收到消息类型 | 动作 |
|--------------|------|
| feishu_otp | 转发OTP给Bastion inbox |
| feishu_command | 解析并转发给对应Agent |
| agent_timeout | 飞书通知用户Agent失联 |
| bastion_disconnect | 飞书请求OTP |
| progress_milestone | 飞书进度通知 |

## 状态更新频率

| 操作 | 频率 | 说明 |
|------|------|------|
| 消息轮询 | 每10秒 | 处理各Agent消息 |
| 状态检查 | 每5秒 | 检查Agent心跳 |
| 心跳更新 | 每5秒 | heartbeat.json |
| 飞书监听 | 后台持续 | 监听用户回复 |
| 飞书通知 | 事件驱动 | 消息触发时发送 |

---

### 循环伪代码

```python
while status != "stopped":
    # 每5秒执行
    check_agent_status()  # 检查各Agent心跳
    
    # 每10秒执行
    if loop_count % 2 == 0:
        poll_messages()  # 轮询各Agent消息队列
        route_messages()  # 路由消息
    
    # 更新心跳
    update_heartbeat()
    
    # 检查飞书指令（后台监听）
    # feishu_listener独立进程
    
    sleep(5)
```

## 启动方式

```bash
# Hermes Session启动Supervisor
# 自动拉起supervisor_loop.py后台进程

# 或手动启动后台进程
python skills/ut/supervisor/scripts/supervisor_loop.py

# 检查状态
python skills/ut/supervisor/scripts/check_all_agents.py
```

## 终端用户指令

用户在飞书群可直接发送：

| 指令 | 动作 |
|------|------|
| `otp 123456` | 转发OTP给Bastion启动daemon |
| `check status` | 发送status_request给所有Agent |
| `pause runner` | 发送pause指令给Runner |
| `resume runner` | 发送resume指令给Runner |
| `stop runner` | 发送stop指令给Runner |

## 禁止操作

- ❌ 不执行测试（Runner职责）
- ❌ 不下载依赖/模型（Environment职责）
- ❌ 不维护容器/环境（Environment职责）
- ❌ 不处理Bastion连接（Bastion职责）
- ❌ 不直接SSH远程机器（通过Agent转发）

## 相关文档

- [message-routing.md](./references/message-routing.md) - 消息路由规则
- [feishu-integration.md](./references/feishu-integration.md) - 飞书集成说明
- [agent-coordination.md](./references/agent-coordination.md) - Agent协调策略
- [agent-config.md](./references/agent-config.md) - Agent配置

---

*创建日期: 2026-06-06*
*版本: 1.0.0*