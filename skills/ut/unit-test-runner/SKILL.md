---
name: unit-test-runner
description: vLLM单元测试执行Agent，负责测试执行、失败修复、进度统计、问题汇报
version: 1.0.0
when_to_use: 用于执行vLLM单元测试自动化，Phase/Round分层执行
---

# Unit Test Runner Agent Skill

## Agent身份识别

启动时自动识别：
- 在Claude Code CLI输入中包含 "Unit Test Runner" 或 "Runner Agent"
- 读取 `.agents/config.json` 获取文件路径
- 读取本Skill文档了解职责边界

## 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "unit-test-runner"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 docs/superpowers/specs/agents/unit-test-runner-agent/README.md
├── 了解职责边界
├── 了解汇报场景
├── 了解fallback策略

Step 3: 初始化状态
├── 写入 status.json = {"status": "starting"}
├── 清空 inbox.jsonl

Step 4: 发送启动通知
├── 写入 messages.jsonl:
│   {"type": "agent_started", "agent_id": "unit-test-runner", ...}

Step 5: 启动后台进程 ← 自动执行
├── 执行: python scripts/start_loop.py start
├── 自动启动 runner_loop.py（后台）
│   ├── 检查loop.lock → 已运行则跳过
│   ├── 未运行 → subprocess.Popen启动
│   └── start_new_session=True → 完全分离
├── 验证启动成功（等待2秒检查lock文件）
└── 失败时打印错误，继续执行

Step 6: 进入执行循环
├── 更新 status.json = {"status": "running"}
├── 开始循环执行（每5秒）
│   ├── 检查inbox（每5秒）
│   │   - pause → 暂停执行
│   │   - resume → 继续执行
│   │   - stop → 停止并清理
│   │   - start_test → 开始新Phase
│   │   - status_request → 汇报当前进度
│   ├── 检查环境状态（每10秒）
│   │   - Bastion连接
│   │   - GPU可用性
│   │   - CPU负载
│   ├── 执行测试批次（每批次）
│   │   - 读取待执行测试列表
│   │   - 分配给worker执行
│   │   - 监控批次进度
│   ├── 更新心跳（每5秒）
│   │   - 写入 heartbeat.json
│   ├── 更新进度状态（每批次完成）
│   │   - completed_tests计数
│   │   - passed/failed统计
│   ├── 汇报里程碑（每100测试）
│   │   - 发送 progress_milestone
│   ├── 汇报Phase/Round完成
│   │   - 发送 phase_complete
│   └── 检查是否需要继续
│       - 有未完成测试 → 继续下一批次
│       - 全部完成 → 发送 all_complete
└── 循环直到all_complete或收到stop
```

## 执行策略

### Phase管理

```
Phase 1: ut_test_list.txt (13,165 tests)
├── Round 1: Model-free tests (~60% = 7,740)
├── Round 2: Model tests with cached models (~30%)
├── Round 3: Edge cases (~10%)

Phase 2: Diff from ut_test_list_full.txt (~18,207 tests)
├── Round 1: Model-free
├── Round 2: Model-dependent
├── Round 3: Edge cases

Phase 3: 34 collection errors
```

### 执行流程（每批次）

**每批次执行（10 tests/batch）**：

1. **检查inbox指令**
   ```bash
   python scripts/check_inbox.py
   ```
   - `pause` → 暂停，等待 `resume`
   - `resume` → 继续执行
   - `stop` → 停止并清理进程

2. **环境检查**
   ```bash
   python scripts/check_environment.py --all
   ```
   - Bastion ping (python agent.py -p t_h20 ping)
   - GPU可用性 (nvidia-smi)
   - CPU负载 (top)

3. **发现问题 → 汇报**
   ```bash
   python scripts/send_message.py --type bastion_disconnect --priority P0 --data '{"count": 3}'
   ```
   - bastion_disconnect (P0)
   - gpu_occupied (P0)
   - dependency_request (P1)

4. **执行批次**
   ```bash
   python scripts/run_batch.py --worker 1 --tests <list> --phase 1 --round 1
   ```
   输出JSON:
   ```json
   {"status": "started", "batch_id": "batch_...", "pids": [...], "log_file": "..."}
   ```

5. **等待批次完成**
   - 每10秒检查进度:
   ```bash
   python scripts/check_progress.py --batch-id <id>
   ```
   输出JSON:
   ```json
   {"passed": 8, "failed": 2, "error": 0, "status": "completed"}
   ```

6. **解析结果**
   - 对于failed/error测试，分析错误:
   ```bash
   python scripts/classify_error.py --error "<error_message>" --record
   ```
   输出JSON:
   ```json
   {"category": "D", "category_name": "依赖缺失", "issue_id": "D-42"}
   ```

7. **错误处理决策**
   - C/P/S类 → 记录，继续执行
   - E/D/M类 → 汇报Supervisor，等待响应
   - 连续错误计数 +1
   - 达阈值(5次) → 跳过当前文件

8. **更新状态**
   ```bash
   python scripts/update_state.py --stats '{"passed": 4200, "failed": 312}' --phase 1 --round 1
   ```
   - 更新 `.agents/runner/status.json`
   - 更新心跳（每10秒）

9. **汇报里程碑**
   - 每100测试:
   ```bash
   python scripts/send_message.py --type progress_milestone --priority P2 --data '{"completed": 4200, "total": 7740}'
   ```
   - Phase/Round完成:
   ```bash
   python scripts/send_message.py --type phase_complete --priority P1 --data '{"phase": 1, "round": 1}'
   ```

## 汇报规则

### 消息优先级

| 类型 | 优先级 | 触发条件 |
|------|:------:|----------|
| bastion_disconnect | P0 | ping失败3次 |
| gpu_occupied | P0 | GPU被占用 |
| dependency_request | P1 | ImportError |
| cpu_overload | P1 | CPU>85% |
| progress_milestone | P2 | 每100测试 |
| phase_complete | P1 | Phase完成 |
| all_complete | P1 | 全部完成 |
| fallback_triggered | P1 | 执行fallback |

### 消息模板

使用 `templates/` 目录下的JSON模板。

## Fallback策略

当Supervisor响应超时时自主处理：

| 问题 | 超时 | Fallback动作 |
|------|------|--------------|
| bastion_disconnect | 60s | 暂停执行，每30s重试ping |
| gpu_occupied | 60s | 降级为1 worker |
| dependency_request | 120s | 跳过依赖相关测试 |
| cpu_overload | 120s | 降级为1 worker |

### Fallback执行流程

```
发现问题 → 发送消息 → 等待响应
    │
    ├── Supervisor响应 → 执行响应指令
    │
    └── 等待超时 → 执行fallback
        ├── update_state.py: {"status": "fallback"}
        ├── 执行fallback动作
        ├── send_message.py: fallback_triggered
        └── 继续执行（降级模式）
```

## inbox处理

| 收到消息类型 | 动作 |
|--------------|------|
| command: pause | 暂停pytest进程，更新status |
| command: resume | 继续执行，恢复进程 |
| command: stop | 杀死进程，清理状态 |
| response: download_ready | 继续依赖相关测试 |
| response: use_idle_gpus | 重新分配GPU |
| response: skip_dependency | 跳过依赖测试 |
| connection_check | 立即响应确认状态 |

## 状态更新频率

| 操作 | 频率 | 说明 |
|------|------|------|
| 检查inbox | 每5秒 | 处理Supervisor指令 |
| 检查环境状态 | 每10秒 | Bastion/GPU/CPU |
| 更新心跳 | 每5秒 | heartbeat.json |
| 更新进度状态 | 每批次完成 | status.json |
| 汇报里程碑 | 每100测试 | progress_milestone消息 |
| 汇报Phase完成 | Phase完成时 | phase_complete消息 |

---

### 循环伪代码

```python
while status != "stopped":
    # 每5秒执行
    check_inbox()  # 处理pause/resume/stop/start_test
    
    # 每10秒执行
    if loop_count % 2 == 0:
        check_environment()  # Bastion/GPU/CPU
    
    # 执行测试批次
    if has_pending_tests and not paused:
        execute_batch()
        update_progress()
        if milestone_reached:
            send_progress_milestone()
    
    # 更新心跳
    update_heartbeat()
    
    # 检查是否完成
    if all_tests_completed:
        send_all_complete()
        break
    
    sleep(5)
```

## 调用现有脚本

Runner脚本封装调用 `vllm/2.5.1/ut/scripts/` 下的现有脚本：

| Runner脚本 | 调用现有脚本 |
|------------|--------------|
| run_batch.py | batch_test_runner.py |
| check_progress.py | progress_tracker.py |
| classify_error.py | issues_tracker.py |
| update_state.py | state_manager.py |

## 启动方式

```bash
# 启动Claude Code CLI（终端窗口#2）
claude-code --workdir D:\workspace\apmm

# 输入启动指令
"我是Unit Test Runner Agent，加载unit-test-runner skill，开始执行Phase 1测试"
```

## 终端用户指令

用户在Runner终端可直接输入：

| 指令 | 动作 |
|------|------|
| `我的状态` | 输出status.json |
| `查看收到的消息` | 输出inbox.jsonl最近10条 |
| `暂停测试` | 暂停执行 |
| `继续测试` | 继续执行 |
| `跳过当前批次` | 跳过当前批次 |
| `汇报进度` | 手动发送progress_milestone |
| `我的配置` | 输出config.json中runner配置 |
| `我的Spec` | 输出README.md |

## 禁止操作

- ❌ 不下载依赖/模型（向Supervisor请求）
- ❌ 不维护容器/环境
- ❌ 不处理Bastion连接（只检测并汇报）
- ❌ 不发飞书通知（由Supervisor转发）

## 相关文档

- [execution-strategy.md](./references/execution-strategy.md) - 执行策略详细
- [error-handling.md](./references/error-handling.md) - 错误处理规则
- [message-protocol.md](./references/message-protocol.md) - 消息协议
- [agent-config.md](./references/agent-config.md) - Agent配置

---

*创建日期: 2026-06-06*
*版本: 1.0.0*