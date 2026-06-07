# 连接监控规则

## 监控目标

| 目标机器 | IP地址 | 用途 |
|----------|--------|------|
| t_h20 | 10.10.154.13 | 测试执行机器（NVIDIA H20-3e） |
| t_ascend | 10.250.121.21 | 联网机器（依赖下载） |

## 监控频率

| 操作 | 频率 |
|------|------|
| ping检查 | 每10秒 |
| daemon检查 | 每30秒 |
| 断连阈值 | 3次失败（30秒） |

## Ping执行命令

```bash
python agent.py -p t_h20 ping
python agent.py -p t_ascend ping
```

## 状态判断

| 响应情况 | 状态 | 延迟阈值 |
|----------|------|----------|
| 响应正常（含pong） | connected | delay < 5000ms |
| 响应延迟过长 | unstable | delay > 5000ms |
| 响应失败/超时 | disconnect | timeout |

## 断连检测

断连判定条件：
- ping连续失败 **3次**
- 累计时间约 **30秒**

断连后动作：
1. 发送 `bastion_disconnect`（P0）
2. 更新 status.json: `{"waiting_for_otp": true}`
3. **仅汇报，等待人工响应**

## 不稳定检测

不稳定判定条件：
- ping响应延迟 > 5000ms

不稳定后动作：
1. 发送 `bastion_unstable`（P1）
2. 记录延迟数据
3. 不中断测试

---

*创建日期: 2026-06-06*