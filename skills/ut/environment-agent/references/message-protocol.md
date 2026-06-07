# 消息协议

## 消息格式

```json
{
  "type": "<消息类型>",
  "priority": "P0/P1/P2",
  "timestamp": "ISO-8601",
  "agent_id": "environment",
  "data": { ... }
}
```

## 消息类型列表

### P0 紧急消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| gpu_intrusion | GPU被非UT进程占用 | 是 |
| container_error | 容器停止/异常 | 是 |
| disk_space_critical | 磁盘使用>95% | 是 |

### P1 重要消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| dependency_failed | ≥10个模型下载失败 | 是 |
| disk_space_warning | 磁盘使用>90% | 是 |

### P2 常规消息

| 类型 | 触发条件 | 需飞书通知 |
|------|----------|:----------:|
| dependency_ready | 单个下载完成 | 否 |
| environment_status | 每5分钟定时汇报 | 否 |
| agent_started | Agent启动 | 否 |

## inbox接收消息

| 类型 | 动作 |
|------|------|
| download_dependency | 启动Python包下载 |
| download_model | 启动HF模型下载 |
| check_gpu_intrusion | 详细检查GPU占用进程 |
| skip_failed | 跳过失败模型，记录skip_manifest |
| retry_failed | 重试下载失败模型 |

---

*创建日期: 2026-06-06*