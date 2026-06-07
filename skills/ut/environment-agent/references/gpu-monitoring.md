# GPU监控规则

## 监控频率

| 操作 | 频率 |
|------|------|
| GPU状态检查 | 每10秒 |
| GPU进程检查 | 仅在发现占用时 |

## GPU状态判断

| 条件 | 状态 |
|------|------|
| 内存空闲 > 100GB 且 利用率 < 5% | 空闲 |
| 内存空闲 ≤ 100GB 或 利用率 ≥ 5% | 占用 |

## UT进程识别

以下进程被视为UT测试进程：
- pytest
- python -m pytest
- vllm

## 抢占检测

检测到非UT进程占用GPU时：
1. 记录进程PID、GPU ID、进程名称
2. 发送 `gpu_intrusion` 消息（P0）
3. **不尝试自动处理**，等待人工协调

## 汇报格式

```json
{
  "type": "gpu_intrusion",
  "priority": "P0",
  "data": {
    "occupied_gpus": ["1", "3"],
    "intrusion_pids": [
      {"pid": "12345", "gpu": "1", "process": "other_process"}
    ],
    "idle_gpus": ["0", "2", "4"]
  }
}
```

---

*创建日期: 2026-06-06*