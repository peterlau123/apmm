# Agent协调策略

## 协调原则

1. **中心化路由**: 所有消息通过Supervisor路由
2. **优先级处理**: P0立即处理，P1/P2延迟处理
3. **异步通信**: 通过文件队列，不直接调用
4. **超时机制**: Agent心跳超时触发告警

## Agent关系图

```
        Supervisor (中心)
            │
    ┌───────┼───────┐
    │       │       │
    ▼       ▼       ▼
Bastion  Runner  Environment
    │       │       │
    │       │       │
    ▼       ▼       ▼
SSH连接  测试执行  GPU/容器
```

## 协调场景

### 场景1: SSH断连
```
Bastion检测断连
    │
    ├→ 发送 bastion_disconnect (P0)
    │
Supervisor收到
    │
    ├→ 飞书通知用户"需要OTP"
    │
用户回复OTP
    │
    ├→ Supervisor转发OTP给Bastion
    │
Bastion使用OTP启动daemon
    │
    ├→ 发送 bastion_recovered
    │
Supervisor飞书通知"恢复"
```

### 场景2: GPU抢占
```
Environment检测GPU抢占
    │
    ├→ 发送 gpu_intrusion (P0)
    │
Supervisor收到
    │
    ├→ 飞书通知用户"GPU被抢占"
    ├→ 发送 gpu_occupied 给Runner
    │
Runner收到
    │
    ├→ 暂停当前测试
    ├→ 使用空闲GPU继续
    │
Environment持续监控
    │
    ├→ GPU恢复空闲 → 发送 gpu_available
    │
Runner恢复全GPU运行
```

### 场景3: 依赖下载
```
Runner执行测试缺少依赖
    │
    ├→ 发送 dependency_request (P1)
    │
Supervisor收到
    │
    ├→ 转发给Environment inbox
    │
Environment收到
    │
    ├→ 下载依赖到t_ascend
    ├→ 发送 dependency_ready
    │
Supervisor转发给Runner
    │
Runner继续执行依赖测试
```

### 场景4: 测试进度
```
Runner每100测试
    │
    ├→ 发送 progress_milestone (P2)
    │
Supervisor收到
    │
    ├→ 飞书通知"进度: X/Y"
    │
RunnerPhase完成
    │
    ├→ 发送 phase_complete (P1)
    │
Supervisor飞书通知"Phase完成"
```

## 冲突处理

| 冲突场景 | 处理策略 |
|-----------|----------|
| GPU抢占 | 仅汇报，等待人工处理 |
| 容器异常 | 仅汇报，等待人工处理 |
| 依赖下载失败 | 跳过相关测试，记录问题 |
| SSH断连 | 汇报，用户提供OTP后恢复 |

---

*创建日期: 2026-06-06*