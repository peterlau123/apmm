# Agent配置

## Agent信息

| 属性 | 值 |
|------|-----|
| Agent ID | unit-test-runner |
| Agent类型 | Claude Code CLI |
| 终端窗口 | #2 |
| 工作目录 | D:\workspace\apmm |
| Skill路径 | skills/ut/unit-test-runner |

## 文件位置

| 文件 | 路径 |
|------|------|
| 状态文件 | .agents/runner/status.json |
| 消息队列 | .agents/runner/messages.jsonl |
| 接收队列 | .agents/runner/inbox.jsonl |
| 心跳文件 | .agents/runner/heartbeat.json |
| 测试Manifest | vllm/2.5.1/ut/test_manifest.json |
| 执行状态 | vllm/2.5.1/ut/execution_state.json |
| 问题记录 | vllm/2.5.1/ut/issues.json |
| 测试日志 | vllm/2.5.1/ut/ut_logs/ |

## 状态更新频率

| 操作 | 频率 |
|------|------|
| status.json更新 | 每批次（~2-3分钟） |
| 消息发送 | 每问题立即发送 |
| 心跳更新 | 每10秒 |
| 进度里程碑 | 每100测试 |

## Fallback超时

| 问题类型 | 等待超时 |
|----------|:--------:|
| bastion_disconnect | 60秒 |
| gpu_occupied | 60秒 |
| dependency_request | 120秒 |
| cpu_overload | 120秒 |

## 现有脚本路径

Runner调用 `vllm/2.5.1/ut/scripts/` 下的现有脚本：

| 现有脚本 | 功能 |
|----------|------|
| test_scheduler.py | Phase管理、调度 |
| batch_test_runner.py | pytest执行 |
| progress_tracker.py | 进度统计 |
| log_manager.py | 日志管理 |
| issues_tracker.py | 问题分类 |
| state_manager.py | 状态持久化 |
| parse_results.py | 结果解析 |

## 启动命令

```bash
# 启动Claude Code CLI（终端窗口#2）
claude-code --workdir D:\workspace\apmm

# 输入启动指令
"我是Unit Test Runner Agent，加载unit-test-runner skill，开始执行Phase 1测试"
```

---

*创建日期: 2026-06-06*