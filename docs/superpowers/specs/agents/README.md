# Multi-Agent协同系统总览

> **⚠️ DEPRECATED - 此文档已过时**
> 
> **最新方案请参考**: [2026-06-08-agent-automation-design.md](./2026-06-08-agent-automation-design.md)
> 
> 原四Agent架构已简化为双Agent架构（Supervisor + Runner）。
> Environment Agent 和 Bastion Agent 已移除，职责合并到 Runner。

---

## 架构变更说明

| 变更 | 原设计 | 新设计 |
|------|--------|--------|
| Agent数量 | 4个 | **2个** |
| Environment Agent | 独立Agent | ❌ 移除 → Runner自处理依赖 |
| Bastion Agent | 独立Agent | ❌ 移除 → Runner通过agent.py连接 |
| 通信复杂度 | 3条通道 | **1条通道** |

---

## 文档索引

| 文档 | 状态 | 说明 |
|------|:----:|------|
| **[../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)** | ✅ Active | **双Agent自动化方案** |
| [unit-test-executor-agent/README.md](unit-test-executor-agent/README.md) | ✅ Active | Runner Agent详细设计 |
| [supervisor-agent/README.md](supervisor-agent/README.md) | ✅ Active | Supervisor Agent详细设计 |
| [inbox-management-analysis.md](inbox-management-analysis.md) | ✅ Active | Inbox消息积压问题分析 |
| [../archive/environment-agent/README.md](../archive/environment-agent/README.md) | ⚠️ Archived | Environment Agent（已废弃） |
| [../archive/bastion-agent/README.md](../archive/bastion-agent/README.md) | ⚠️ Archived | Bastion Agent（已废弃） |

---

## 原设计（已废弃）

本系统采用 **1 Hermes Supervisor + 3 Claude Code Agent** 的架构，实现vLLM单元测试的自动化执行、环境维护和连接监控。

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent协同架构                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  终端窗口 #1: Hermes Agent (Supervisor)                          │
│  ├── 职责: 协调、消息路由、飞书通知                               │
│  ├── 通信: 飞书双向通信（接收用户指令）                           │
│  └── 监控: 轮询各Agent状态                                        │
│                                                                  │
│  终端窗口 #2: Claude Code CLI (Unit Test Runner)                 │
│  ├── 职责: 执行测试、修复失败、统计进度                           │
│  └── 汇报: 通过共享文件与Supervisor通信                           │
│                                                                  │
│  终端窗口 #3: Claude Code CLI (Environment Agent)                │
│  ├── 职责: GPU监控、容器维护、依赖下载                            │
│  └── 汇报: 通过共享文件与Supervisor通信                           │
│                                                                  │
│  终端窗口 #4: Claude Code CLI (Bastion Agent)                    │
│  ├── 职责: Bastion连接监控、断连恢复                              │
│  ├── 特殊: 支持OTP验证码传递                                      │
│  └── 汇报: 通过共享文件与Supervisor通信                           │
│                                                                  │
│  共享目录: .agents/                                               │
│  飞书群: oc_2e75db818ac1792238037a704b4d32d3                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent职责边界

| Agent | 类型 | 核心职责 | 不负责 |
|-------|------|----------|--------|
| **Supervisor** | Hermes | 协调、消息路由、飞书通知、用户接口 | ❌ 不执行测试、不监控环境、不处理断连 |
| **Unit Test Runner** | Claude Code | 测试执行、失败修复、进度统计 | ❌ 不下载依赖、不维护环境、不发飞书 |
| **Environment** | Claude Code | GPU监控、容器维护、依赖下载 | ❌ 不执行测试、不处理断连、不发飞书 |
| **Bastion** | Claude Code | 连接监控、断连恢复、OTP处理 | ❌ 不执行测试、不监控GPU、不发飞书 |

---

## 通信机制

### 共享文件通信

所有Agent通过 `.agents/` 目录下的共享文件通信：

```
.agents/
├── config.json              # 全局配置（Agent文件位置映射）
├── global_state.json        # 全局状态汇总（Supervisor维护）
│
├── runner/
│   ├── status.json          # Runner当前状态
│   ├── messages.jsonl       # Runner → Supervisor 消息队列
│   └── inbox.jsonl          # Supervisor → Runner 消息队列
│
├── environment/
│   ├── status.json          # Environment当前状态
│   ├── messages.jsonl       # Environment → Supervisor 消息队列
│   └── inbox.jsonl          # Supervisor → Environment 消息队列
│
├── bastion/
│   ├── status.json          # Bastion当前状态
│   ├── messages.jsonl       # Bastion → Supervisor 消息队列
│   └── inbox.jsonl          # Supervisor → Bastion 消息队列
│
├── supervisor/
│   ├── status.json          # Supervisor当前状态
│   └── heartbeat.json       # 心跳时间戳
│
└── archive/                 # 已处理消息归档
```

### 飞书双向通信

用户通过飞书群与Supervisor Agent通信：

- **用户 → Supervisor**: 发送指令（如 "进度"、"OTP 123456"）
- **Supervisor → 用户**: 发送通知卡片（进度、告警、状态）

---

## 启动指南

### 启动顺序（不固定）

用户可按任意顺序启动4个Agent：

```bash
# 终端窗口 #1: 启动Supervisor (Hermes)
hermes
# 或直接在此session工作

# 终端窗口 #2: 启动Unit Test Runner (Claude Code)
claude-code --workdir D:\workspace\apmm
# 输入: "我是Unit Test Runner Agent，启动测试执行..."

# 终端窗口 #3: 启动Environment Agent (Claude Code)
claude-code --workdir D:\workspace\apmm
# 输入: "我是Environment Agent，启动环境监控..."

# 终端窗口 #4: 启动Bastion Agent (Claude Code)
claude-code --workdir D:\workspace\apmm
# 输入: "我是Bastion Agent，启动连接监控..."
```

### Agent自识别流程

每个Agent启动时自动：
1. 读取 `.agents/config.json` 获取自己的文件位置
2. 读取对应的Spec文档了解职责
3. 初始化状态文件
4. 发送启动通知给Supervisor

---

## 用户介入方式

### 飞书介入（主要）

在飞书群发送消息：

| 指令 | 示例 | 说明 |
|------|------|------|
| 状态查询 | `状态`、`Runner状态`、`进度` | Supervisor返回状态卡片 |
| 控制指令 | `暂停Runner`、`继续Runner` | 转发指令给对应Agent |
| OTP验证码 | `OTP 123456` | 转发给Bastion Agent |
| 下载请求 | `下载模型 meta-llama/Llama-3.2-1B` | 转发给Environment Agent |

### 终端介入（备用）

直接在Agent终端窗口输入指令：

- **Supervisor终端**: `查看当前状态`、`暂停Runner`
- **Runner终端**: `暂停测试`、`我的状态`
- **Environment终端**: `GPU状态`、`下载模型 xxx`
- **Bastion终端**: `重连`、`我的状态`

---

## 文档索引

| 文档 | 位置 | 说明 |
|------|------|------|
| 全局架构 | [global-architecture.md](./global-architecture.md) | 通信协议、状态格式、消息类型 |
| Supervisor Agent | [supervisor-agent/README.md](./supervisor-agent/README.md) | 消息路由、飞书通知、失联检测 |
| Unit Test Runner | [unit-test-executor-agent/README.md](./unit-test-executor-agent/README.md) | 测试执行、进度追踪、fallback策略 |
| Environment Agent | [environment-agent/README.md](./environment-agent/README.md) | GPU监控、容器维护、依赖下载 |
| Bastion Agent | [bastion-agent/README.md](./bastion-agent/README.md) | 连接监控、断连恢复、OTP处理 |

---

## 现有Spec文档（已迁移）

以下文档已整合到Unit Test Runner Agent设计中：

- [test-automation-design.md](./unit-test-executor-agent/test-automation-design.md) - 测试自动化架构
- [test-execution-plan.md](./unit-test-executor-agent/test-execution-plan.md) - 多轮执行策略
- [agent-communication-design.md](./unit-test-executor-agent/agent-communication.md) - Runner通信协议
- [feishu-notification-design.md](./supervisor-agent/feishu-notification.md) - 飞书通知模板

---

*创建日期: 2026-06-06*
*状态: Draft - Pending Review*