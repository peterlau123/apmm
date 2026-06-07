# Agent Daemon 使用指南（apmm版本）

## 架构概述

```
agent_daemon.py (守护进程)
    ├── 自动启动所有enabled Agent
    ├── 健康监控（每10秒）
    ├── 自动重启（崩溃/心跳超时）
    └── 飞书告警
```

---

## 快速开始

### 1. 启动守护进程

```powershell
# 方式1：前台运行（调试用）
python D:\workspace\apmm\.agents\daemon\agent_daemon.py

# 方式2：后台运行（生产用）
start /min pythonw D:\workspace\apmm\.agents\daemon\agent_daemon.py

# 方式3：通过启动脚本
.\setup_autostart.ps1
```

### 2. 检查Agent状态

```powershell
python D:\workspace\apmm\.agents\daemon\check_status.py
```

---

## Agent路径映射

| Agent | 路径 | 说明 |
|-------|------|------|
| Supervisor | `skills/ut/supervisor/scripts/supervisor_loop.py` | 监控Agent |
| Runner | `skills/ut/unit-test-runner/scripts/start_loop.py` | 测试执行 |
| Environment | 按需启动 | GPU/容器监控 |
| Bastion | 按需启动 | SSH堡垒机 |

---

## 配置文件

### config.json位置

```
D:\workspace\apmm\.agents\config.json
```

### Agent启用/禁用

```json
{
  "agents": {
    "supervisor": { "enabled": true },
    "unit-test-runner": { "enabled": true },
    "environment": { "enabled": false },
    "bastion": { "enabled": false }
  }
}
```

---

## 监控参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| health_check_interval | 10秒 | 健康检查频率 |
| heartbeat_timeout | 60秒 | 心跳超时阈值 |
| restart_delay | 5秒 | 重启延迟 |
| max_restart_attempts | 3次 | 最大重启次数 |

---

## 日志文件

```
D:\workspace\apmm\.agents\daemon\daemon.log
D:\workspace\apmm\.agents\logs\supervisor.log
D:\workspace\apmm\.agents\logs\runner.log
```

---

## Windows任务计划配置（开机自启）

```powershell
.\setup_autostart.ps1
```

管理命令：
```powershell
启动: Start-ScheduledTask -TaskName AgentDaemon-apmm
停止: Stop-ScheduledTask -TaskName AgentDaemon-apmm
状态: Get-ScheduledTask -TaskName AgentDaemon-apmm
删除: Unregister-ScheduledTask -TaskName AgentDaemon-apmm
```

---

## 下一步

1. **测试守护进程**
   ```powershell
   python D:\workspace\apmm\.agents\daemon\agent_daemon.py
   ```

2. **检查Agent状态**
   ```powershell
   python D:\workspace\apmm\.agents\daemon\check_status.py
   ```

3. **配置开机自启**
   ```powershell
   .\setup_autostart.ps1
   ```