# Supervisor Agent 设计

> **Agent协同系统 - Supervisor Agent (Hermes)**
> **职责: 协调、消息路由、飞书通知、用户接口**
> **运行模式: 混合模式（Cron Job后台 + Session交互）**
> **创建日期: 2026-06-06**

---

## Agent信息

| 属性 | 值 |
|------|-----|
| Agent ID: workflow` |
| Agent类型 | Hermes |
| 终端窗口 | #1 |
| 状态文件 | `.agents/supervisor/status.json` |
| 心跳文件 | `.agents/supervisor/heartbeat.json` |
| Spec文件 | `docs/superpowers/specs/agents/supervisor-agent/README.md` |

---

## 运行模式

Supervisor Agent 采用 **前台循环模式** 运行：

```
┌─────────────────────────────────────────────────────────────────┐
│                    前台循环模式                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 Hermes Session (前台循环)                │   │
│  │                                                          │   │
│  │  workflow_loop.py（前台运行）                          │   │
│  │  ├── 消息轮询 (每10秒)                                   │   │
│  │  ├── 状态检查 (每5秒)                                    │   │
│  │  ├── status.json轮询 (每30秒，兜底)                      │   │
│  │  ├── 飞书监听 (每60秒)                                   │   │
│  │  ├── 心跳更新 (每循环)                                   │   │
│  │  │                                                      │   │
│  │  功能:                                                   │   │
│  │  ├── 自动轮询各Agent消息                                  │   │
│  │  ├── 自动转发路由                                         │   │
│  │  ├── 自动发送飞书通知                                     │   │
│  │  ├── 自动检测Agent失联                                    │   │
│  │  ├── 自动处理飞书用户指令                                 │   │
│  │  ├── 自动启动Runner Agent                                 │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                    │
│                           ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 Runner Agent (Claude Code CLI)           │   │
│  │                                                          │   │
│  │  Supervisor自动启动，无需手动干预                          │   │
│  │  ├── start_runner_agent.py start                         │   │
│  │  ├── Claude Code CLI进程                                 │   │
│  │  ├── 执行测试并更新状态文件                               │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心职责

```
┌─────────────────────────────────────────────────────────────────┐
│                    Supervisor Agent职责                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ✅ 消息路由（Cron自动）                                         │
│  ├── 轮询各Agent的messages.jsonl                                │
│  ├── 按优先级排序处理                                            │
│  ├── 转发消息到对应Agent的inbox.jsonl                            │
│  └── 归档已处理消息                                              │
│                                                                  │
│  ✅ 飞书通知（Cron自动）                                         │
│  ├── 进度里程碑卡片                                              │
│  ├── 告警卡片（需人工介入）                                       │
│  ├── 状态查询响应卡片                                            │
│  └── OTP确认卡片                                                 │
│                                                                  │
│  ✅ 飞书指令处理（Cron自动）                                      │
│  ├── 状态查询 → 自动返回                                         │
│  ├── OTP验证码 → 自动转发                                        │
│  ├── 控制指令 → 自动转发                                         │
│  ├── 下载请求 → 自动转发                                         │
│  │  （所有指令自动执行，事后通知）                                │
│                                                                  │
│  ✅ 全局状态管理（Cron自动）                                     │
│  ├── 维护global_state.json                                      │
│  ├── 汇总各Agent状态                                             │
│  ├── 检测Agent失联                                               │
│  └── 更新心跳                                                    │
│                                                                  │
│  ✅ 用户接口（Session交互）                                      │
│  ├── 用户主动查看状态                                            │
│  ├── 用户主动输入指令                                            │
│  ├── 接收飞书事后通知                                            │
│  └── Session重启状态恢复                                         │
│                                                                  │
│  ❌ 不负责                                                       │
│  ├── 不执行测试                                                  │
│  ├── 不监控GPU/容器                                              │
│  ├── 不处理Bastion断连（只转发告警）                              │
│  ├── 不下载依赖/模型                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 循环脚本配置

### 统一循环脚本

Supervisor使用统一循环脚本 `workflow_loop.py`：

| 轮询任务 | 频率 | 执行方式 | 功能 |
|----------|------|----------|------|
| 消息轮询 | 10秒 | subprocess调用 | 消息轮询、路由转发 |
| 状态检查 | 5秒 | subprocess调用 | 状态检查、失联检测 |
| status.json轮询 | 30秒 | 内部函数 | Runner状态变化检测（兜底） |
| 飞书监听 | 60秒 | subprocess调用 | 飞书监听、指令处理 |
| 心跳更新 | 每循环 | 内部函数 | heartbeat.json更新 |

### 脚本文件

```
scripts/
├── workflow_loop.py           # 统一循环脚本（前台运行）
├── start_runner_agent.py        # Runner启动脚本
├── supervisor_message_poll.py   # 消息轮询脚本
├── supervisor_status_check.py   # 状态检查脚本
├── supervisor_feishu_listen.py  # 飞书监听脚本
├── feishu_api.py                # 飞书API封装
├── message_router.py            # 辅助函数
└── check_all_agents.py          # Agent状态检查
```

### 启动Runner

Supervisor在启动时自动检查并启动Runner：

```
workflow_loop.py 启动时:
├── 检查Runner状态文件
├── Runner未运行 → 调用 start_runner_agent.py start
├── 启动Claude Code CLI进程
├── Runner已运行 → 跳过启动
└── Runner PID记录到 status.json
```

---

## 消息轮询脚本详情

### supervisor_message_poll.py

**执行频率**: 每10秒

**执行流程**:
```
Step 1: 读取各Agent消息队列
├── runner/messages.jsonl
├── environment/messages.jsonl
├── bastion/messages.jsonl
└── 过滤新消息（自上次轮询后）

Step 2: 按优先级排序
├── P0 → 立即处理
├── P1 → 正常处理
├── P2 → 批量处理

Step 3: 消息路由
├── 根据消息类型路由到对应inbox
├── 发送飞书通知（按模板）

Step 4: 更新global_state.json
Step 5: 归档已处理消息
Step 6: 更新心跳
```

**消息路由规则**:
| 消息类型 | 路由目标 | 飞书通知 |
|----------|----------|----------|
| bastion_disconnect | bastion/inbox | 告警卡片 |
| dependency_request | environment + runner | 通知卡片 |
| gpu_occupied | environment + runner | 告警卡片 |
| gpu_intrusion | 无（仅飞书） | 告警卡片（需人工） |
| dependency_ready | runner/inbox | 通知卡片 |
| otp_required | 无（仅飞书） | 告警卡片（需人工） |
| bastion_recovered | runner/inbox | 通知卡片 |
| progress_milestone | 无（仅飞书） | 进度卡片 |
| phase_complete | 无（仅飞书） | 完成卡片 |

---

## 状态检查脚本详情

### supervisor_status_check.py

**执行频率**: 每30秒

**执行流程**:
```
Step 1: 读取各Agent状态文件
├── runner/status.json
├── environment/status.json
├── bastion/status.json

Step 2: 检测Agent失联
├── 计算last_update距今时间
├── >60秒 → Level1 (可疑) → 发飞书警告
├── >120秒 → Level2 (确认失联) → 发飞书告警 + 写入inbox请求确认
├── >180秒 → Level3 (严重失联) → 发飞书紧急告警

Step 3: 更新global_state.json
├── 各Agent状态
├── connection_health
├── system_health

Step 4: 汇总测试进度
├── 从runner/status.json读取
├── 更新test_progress部分

Step 5: 检查待处理请求
├── 超时未处理 → 发飞书提醒
```

---

## 飞书监听脚本详情

### supervisor_feishu_listen.py

**执行频率**: 每60秒

**执行流程**:
```
Step 1: 获取飞书群最新消息
├── 调用飞书API
├── 过滤已处理消息

Step 2: 解析用户指令（正则匹配）
├── OTP验证码 → /^otp\s+\d{6}$/
├── 状态查询 → /状态|进度/
├── 控制指令 → /暂停|继续|停止/
├── 下载请求 → /下载模型/

Step 3: 执行指令
├── otp_code → 写入bastion/inbox + 发飞书确认
├── query_status → 读取global_state + 发状态卡片
├── pause_runner → 写入runner/inbox + 发确认卡片
├── download_model → 写入environment/inbox + 发确认卡片

Step 4: 归档已处理消息ID
```

**支持的飞书指令**:
| 用户发送 | 解析结果 | 动作 |
|----------|----------|------|
| `OTP 123456` | otp_code | 转发给Bastion + 发确认 |
| `状态` | query_status | 发状态卡片 |
| `进度` | query_progress | 发进度卡片 |
| `暂停Runner` | pause_runner | 转发给Runner + 发确认 |
| `继续Runner` | resume_runner | 转发给Runner + 发确认 |
| `下载模型 xxx` | download_model | 转发给Environment + 发确认 |

---

## Session交互

### 用户主动指令

用户在Hermes Session中可直接输入：

| 指令 | 动作 |
|------|------|
| `查看当前状态` | 输出global_state.json摘要 |
| `查看Runner状态` | 输出runner/status.json |
| `查看进度` | 输出test_progress详情 |
| `查看GPU状态` | 输出environment GPU信息 |
| `查看Bastion状态` | 输出bastion连接信息 |
| `暂停Runner` | 写入runner/inbox + 输出确认 |
| `继续Runner` | 写入runner/inbox + 输出确认 |
| `发送测试飞书` | 发送demo飞书卡片 |
| `查看待处理请求` | 输出pending_requests列表 |
| `查看最近告警` | 输出recent_alerts列表 |

### 状态恢复流程

```
Session重启 →
├── 读取.agents/config.json
├── 读取.agents/global_state.json
├── 显示Agent状态汇总
├── 检查pending_requests → 有则提示
├── 检查recent_alerts → 有则提示
└── 等待用户指令
```

---

## Agent失联处理

### 失联等级

| 等级 | 条件 | 动作 |
|------|------|------|
| Level 1 (可疑) | 60秒未更新 | 发飞书警告 |
| Level 2 (确认失联) | 120秒未更新 | 发飞书告警 + 写入inbox请求确认 |
| Level 3 (严重失联) | 180秒未更新 | 发飞书紧急告警 + 提示用户检查终端 |

---

## 相关文档

- [message-routing.md](./message-routing.md) - 详细消息路由逻辑
- [feishu-notification.md](./feishu-notification.md) - 飞书通知模板

---

## 脚本文件

详细脚本代码见：
- `scripts/supervisor_message_poll.py`
- `scripts/supervisor_status_check.py`
- `scripts/supervisor_feishu_listen.py`
- `scripts/feishu_api.py`
---

*创建日期: 2026-06-06*
*更新日期: 2026-06-08*
*状态: 已实现 - workflow_loop.py + start_runner_agent.py*