# Agent Inbox 消息积压问题分析

## 问题描述

各 Agent inbox 积压了大量 `connection_check` 消息：
- Supervisor: 300 条
- Bastion: 1019 条
- Environment: 611 条
- Unit-test-runner: 3 条（相对正常）

## 根因分析

### 1. `connection_check` 无限写入

**位置**: `skills/ut/supervisor/scripts/supervisor_status_check.py` 第 81-88 行

```python
if level in ["disconnected", "critical"]:
    write_to_inbox(agent_id, {
        "type": "connection_check",
        "request": "please_confirm_status",
        "level": level,
        "elapsed_seconds": elapsed,
    })
```

**问题**:
- 检测到 Agent 失联后，每 30 秒检查时都写入一条消息
- Agent 不运行时无法处理，消息无限积压
- elapsed_seconds 从 120 → 180 → 46186 → ...

### 2. 消息队列职责混乱

| 文件 | 设计意图 | 实际问题 |
|-----|---------|---------|
| `messages.jsonl` | Agent 发出的消息 | Supervisor 读取，正确 |
| `inbox.jsonl` | Agent 收到的消息 | Supervisor 写入，Agent 不运行时积压 |

**设计缺陷**: 
- Supervisor 只处理 `messages.jsonl`（Agent 发出的）
- 但向 `inbox.jsonl` 写入（Agent 收到的）
- 没有清理机制，Agent 不运行时消息积压

### 3. 路径不一致

| 脚本使用 | 实际目录 |
|---------|---------|
| `.agents/runner/` | `.agents/unit-test-runner/` |

导致读取文件位置错误。

---

## 改进方案

### 方案A: 消息写入限制（推荐）

**修改 `supervisor_status_check.py`**:

```python
# 新增：记录上次写入 connection_check 的时间
LAST_CHECK_FILE = AGENTS_DIR / "archive" / "last_connection_check.json"

def should_write_connection_check(agent_id):
    """检查是否应该写入 connection_check（避免无限写入）"""
    last_checks = read_json(LAST_CHECK_FILE)
    last_time = last_checks.get(agent_id)
    
    if last_time:
        elapsed_since_last_check = time_since(last_time)
        # 限制：同一 Agent 每 5 分钟最多写入一次
        if elapsed_since_last_check < 300:
            return False
    
    return True

def handle_disconnect(agent_id, health):
    level = health["level"]
    
    if level in ["disconnected", "critical"]:
        if should_write_connection_check(agent_id):
            write_to_inbox(agent_id, {...})
            # 更新记录
            last_checks = read_json(LAST_CHECK_FILE)
            last_checks[agent_id] = datetime.now().isoformat()
            write_json(LAST_CHECK_FILE, last_checks)
```

**优点**: 
- 简单，不需要改动 Agent 循环
- 同一 Agent 每 5 分钟最多收到一条 `connection_check`
- 积压量减少 90%

### 方案B: Inbox 自动清理

**新增清理脚本**:

```python
# scripts/cleanup_stale_inbox.py
def cleanup_inbox(agent_id, max_age_hours=2):
    """清理超过指定时间的 inbox 消息"""
    inbox_file = AGENTS_DIR / agent_id / "inbox.jsonl"
    
    # 读取所有消息
    messages = []
    with open(inbox_file) as f:
        for line in f:
            msg = json.loads(line)
            msg_time = msg.get("timestamp")
            if msg_time:
                elapsed = time_since(msg_time)
                if elapsed < max_age_hours * 3600:
                    messages.append(msg)
    
    # 重写 inbox，只保留新鲜消息
    with open(inbox_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
```

**优点**: 
- 主动清理，避免文件过大
- 可以由 Supervisor 定期调用

### 方案C: 消息队列分离

**重新设计消息队列职责**:

```
.agents/{agent}/
├── inbox.jsonl          # Agent 收到的消息（Supervisor 写入）
├── processed_inbox.jsonl # 已处理的消息（Agent 写入）
├── messages.jsonl        # Agent 发出的消息（Supervisor 读取）
└── status.json          # Agent 状态
```

**流程**:
1. Agent 循环读取 `inbox.jsonl`
2. 处理后将消息移入 `processed_inbox.jsonl`
3. Supervisor 可检查 `processed_inbox.jsonl` 确认消息已处理
4. `inbox.jsonl` 保持小体积

### 方案D: 路径修正

**统一 Agent 目录命名**:

```python
AGENT_DIR_NAMES = {
    "unit-test-executor": "unit-test-executor",  # 修正
    "environment": "environment",
    "bastion": "bastion",
}
```

---

## 推荐实施顺序

1. **立即修复**: 方案A（消息写入限制） + 方案D（路径修正）
2. **中期优化**: 方案B（Inbox 自动清理）
3. **长期重构**: 方案C（消息队列分离）

---

## 频率建议

| 操作 | 当前频率 | 建议频率 |
|-----|---------|---------|
| connection_check 写入 | 失联时每 30秒 | 失联时每 5分钟 |
| inbox 清理 | 无 | 每 1小时 |
| 消息轮询 | 每 10秒 | 保持 |
| 状态检查 | 每 30秒 | 保持 |

---

*分析日期: 2026-06-07*