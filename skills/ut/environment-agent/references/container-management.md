# 容器管理规则

## 监控容器

| 容器名 | 用途 | 监控 |
|--------|------|------|
| v0.13.0_torch2.5.1_compile | **单元测试运行** | 必须监控 |

## 监控频率

| 操作 | 频率 |
|------|------|
| 容器状态检查 | 每30秒 |

## 容器状态判断

| Docker Status | Agent状态 |
|---------------|-----------|
| Up X hours/minutes | running (健康) |
| Exited | stopped (异常) |
| 未找到 | not_found (异常) |

## 异常处理

检测到容器异常时：
1. 发送 `container_error` 消息（P0）
2. **不尝试自动重启**，等待人工处理

## 汇报格式

```json
{
  "type": "container_error",
  "priority": "P0",
  "data": {
    "container": "v0.13.0_torch2.5.1_compile",
    "status": "stopped",
    "docker_status": "Exited (1) 2 hours ago"
  }
}
```

---

*创建日期: 2026-06-06*