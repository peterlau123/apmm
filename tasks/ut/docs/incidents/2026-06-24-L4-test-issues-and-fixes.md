# L4 测试问题总结与修复报告

**日期**: 2026-06-24
**run_id**: ut-20260624-212040
**测试配置**: workflow.l4.yaml (L4 frozen)
**测试清单**: l3_retry_subset.txt (3 个测试)
**飞书对话**：tasks\ut\docs\incidents\2026-06-24-dialogue-with-ut-supervisor.md
---

## 1. 遇到的问题

### 1.1 PYTHONPATH 泄漏问题 ⚠️ **已修复**

| 项目 | 详情 |
|---|---|
| **描述** | Hermes Gateway worker 继承了 Hermes venv 的 PYTHONPATH，导致 jsonschema 模块无法加载 |
| **原因** | Worker scripts 在 Hermes Gateway profile 中运行时，环境变量从父进程泄漏 |
| **错误信息** | `ModuleNotFoundError: No module named 'jsonschema'` |
| **影响** | Orchestrator worker 无法执行 `generate_batch.py`，batch 选择失败 |
| **修复方案** | 在所有 Worker scripts 开头添加显式清除 PYTHONPATH 的代码 |
| **修复时间** | 2026-06-24 21:23 |

**修复代码示例**（已应用到所有 Worker scripts）:
```python
import os
import sys
# Clear PYTHONPATH inherited from Hermes venv (see SKILL pitfall)
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']
```

---

### 1.2 依赖链 race condition ⚠️ **已手动修复**

| 项目 | 详情 |
|---|---|
| **描述** | Fixer 在 Executor 完成前就运行了 |
| **原因** | 手动创建 batch 时依赖链设置不当，Fixer 任务没有正确等待 Executor |
| **影响** | Fixer 处理了空的 `batch_results.json`，manifest 更新不完整 |
| **修复方案** | 重新创建正确的依赖链：orchestrator → executor → fixer |
| **修复时间** | 2026-06-24 21:40 |

**正确依赖链结构**:
```
orchestrator_task (t_xxx)
    ↓ depends_on
executor_task (t_yyy)
    ↓ depends_on
fixer_task (t_zzz)
```

---

### 1.3 Blocked Kanban 任务 ⚠️ **已手动修复**

| 项目 | 详情 |
|---|---|
| **描述** | Kanban 任务被 blocked，Gateway dispatcher 无法调度 |
| **原因** | Orchestrator worker 执行失败后任务被 blocked |
| **影响** | Workflow 无法继续下一轮迭代 |
| **修复方案** | 使用 `hermes kanban unblock <task_id>` 命令 |
| **修复时间** | 2026-06-24 21:45 |

---

### 1.4 Watchdog 超时问题 ⚠️ **待调查**

| 项目 | 详情 |
|---|---|
| **描述** | 所有 3 个测试在 batch_0001 和 batch_0002 都超时（300s watchdog SIGKILL） |
| **可能原因** | 1. 测试本身执行时间超过 300s<br>2. 远程服务器 GPU 资源不足<br>3. Docker 容器配置问题<br>4. Bastion daemon SSH socket closed |
| **影响** | 测试被强制终止，最终被标记为 `ignored`（max retry exceeded） |
| **修复方案** | 需要调查具体原因：<br>1. 检查测试本身是否需要更长执行时间<br>2. 检查远程服务器 GPU 状态<br>3. 检查 Bastion daemon 连接稳定性<br>4. 调整 timeout 配置（如需要） |
| **配置参数** | `timeout: 600`, `pytest_idle_timeout: 120`, watchdog: 300s |

---

### 1.5 Manifest 更新不完整 ⚠️ **已手动修复**

| 项目 | 详情 |
|---|---|
| **描述** | Orchestrator worker 没有正确更新 manifest stats |
| **原因** | Worker 执行中途失败（PYTHONPATH 问题），manifest 状态未同步 |
| **影响** | `workflow_state.json` 的 stats 显示过时数据 |
| **修复方案** | 手动修复 `manifest.json` 和 `workflow_state.json` |
| **修复时间** | 2026-06-24 21:50 |

---

### 1.6 状态机互锁问题 ⚠️ **已手动修复**

| 项目 | 详情 |
|---|---|
| **描述** | 同时有多个 workflow running 状态，违反 §3.A 互锁规则 |
| **原因** | 之前的 workflow `ut-e2e-bugfix-20260624` 未正确终止 |
| **影响** | 新 workflow 无法正常启动 |
| **修复方案** | 手动将旧 workflow 的 `status` 改为 `stopped` |
| **修复时间** | 2026-06-24 21:15 |

---

## 2. 修改的文件

### 2.1 Worker scripts PYTHONPATH 修复（已应用）

| 文件路径 | 修改内容 | 所属 SKILL |
|---|---|---|
| `skills/ut/batch-selector/scripts/generate_batch.py` | 开头添加 PYTHONPATH 清除 | batch-selector |
| `skills/ut/unit-test-executor/scripts/execute_batch.py` | 开头添加 PYTHONPATH 清除 | unit-test-executor |
| `skills/ut/failure-handler/scripts/analyze_failures.py` | 开头添加 PYTHONPATH 清除 | failure-handler |
| `skills/ut/failure-handler/scripts/generate_handled_manifest.py` | 开头添加 PYTHONPATH 清除 | failure-handler |
| `skills/ut/manifest-updater/scripts/update_manifest.py` | 开头添加 PYTHONPATH 清除 | manifest-updater |
| `skills/ut/manifest-updater/scripts/update_status.py` | 开头添加 PYTHONPATH 清除 | manifest-updater |

**修改模式**（统一应用）:
```diff
 import os
 import sys
+# Clear PYTHONPATH inherited from Hermes venv (see SKILL pitfall)
+if 'PYTHONPATH' in os.environ:
+    del os.environ['PYTHONPATH']
```

---

### 2.2 状态文件修复（临时手动修复）

| 文件路径 | 修改内容 | 备注 |
|---|---|---|
| `runs/ut-20260624-212040/workflow_state.json` | 更新 stats 和 iteration | 手动修复 |
| `runs/ut-20260624-212040/manifest.json` | 更新 statistics 和 test status | 手动修复 |

---

### 2.3 Memory 更新（持久化）

已更新 memory 记录 PYTHONPATH 泄漏问题和修复方案，确保后续 session 能自动处理。

---

## 3. 待优化的方面

### 3.1 PYTHONPATH 环境隔离 🔧 **高优先级**

| 问题 | 建议 |
|---|---|
| Worker scripts 仍需手动清除 PYTHONPATH | 1. 在 Gateway profile 配置层面解决（推荐）<br>2. 或在 `hermes_runner.py` 中统一处理 |
| SKILL 文档未明确记录此问题 | 更新所有 Worker SKILL 的 pitfall 章节，记录 PYTHONPATH 泄漏问题和修复方案 |

**建议修改**:
- `skills/ut/batch-selector/SKILL.md` → 添加 pitfall #1: PYTHONPATH 泄漏
- `skills/ut/unit-test-executor/SKILL.md` → 添加 pitfall #8: PYTHONPATH 泄漏
- `skills/ut/failure-handler/SKILL.md` → 添加 pitfall
- `skills/ut/manifest-updater/SKILL.md` → 添加 pitfall

---

### 3.2 Kanban 任务调度优化 🔧 **高优先级**

| 问题 | 建议 |
|---|---|
| Blocked 任务需要手动 unblock | 1. 在 Orchestrator worker 失败后自动 retry 或 report error<br>2. Gateway dispatcher 增加 auto-unblock 逻辑（谨慎） |
| 依赖链 race condition | 1. 确保 Fixer 任务正确等待 Executor 完成<br>2. 在 Executor 完成 card 中包含 `batch_results.json` 状态验证 |
| 任务失败后 workflow 状态未同步 | 1. Worker 失败时发送飞书错误卡片<br>2. Supervisor 增加任务状态监控逻辑 |

---

### 3.3 远程测试超时机制 🔧 **中优先级**

| 问题 | 建议 |
|---|---|
| 300s watchdog 可能过于严格 | 1. 调查测试实际执行时间<br>2. 调整 `timeout` 和 `pytest_idle_timeout` 配置<br>3. 增加 `batch_size` 减少单次执行压力 |
| Bastion daemon 连接不稳定 | 1. 优化 heartbeat 机制<br>2. 增加 daemon 重连 retry logic<br>3. 检查 SSH socket closed 根因 |

**当前配置** (workflow.l4.yaml):
```yaml
timeout: 600          # wall-clock 兜底
pytest_idle_timeout: 120  # 无日志活动超时 → idle kill
# watchdog: 300s (hardcoded in execute_batch.py)
```

---

### 3.4 Orchestrator worker 验证增强 🔧 **中优先级**

| 问题 | 建议 |
|---|---|
| Round 转换间缺少状态验证 | 1. 在 Round 开始前验证 Gateway 状态<br>2. 在 Round 结束后验证 manifest 更新完整性 |
| Worker 失败导致 manifest 更新不完整 | 1. 增加 manifest 更新 transaction 机制<br>2. 添加状态一致性检查函数 |
| 缺少 state consistency check | 1. 在 `hermes_runner.py` 中添加 `verify_state_consistency()` 函数<br>2. 每轮迭代结束后调用 |

---

### 3.5 飞书卡片更新优化 🔧 **低优先级**

| 问题 | 建议 |
|---|---|
| 进度卡片更新延迟 | 1. 在关键节点发送卡片：<br>   - Round 开始<br>   - batch 完成<br>   - Gateway 状态变化<br>   - OTP 请求<br>2. 增加 card update interval 配置 |
| 缺少实时状态推送 | 1. 增加 WebSocket 推送（可选）<br>2. 或增加飞书消息订阅机制 |

---

### 3.6 状态机互锁机制优化 🔧 **低优先级**

| 问题 | 建议 |
|---|---|
| 同时有多个 running workflow | 1. 在 `init_or_resume` 中增加 running workflow 检测<br>2. 提示用户选择：结束旧 workflow 或取消新 workflow |
| 需要手动修改 workflow_state.json | 1. 增加 `hermes_runner.stop_workflow(run_dir)` 函数<br>2. 提供 CLI 命令：`hermes ut stop <run_dir>` |

---

### 3.7 Bastion daemon 管理 🔧 **中优先级**

| 问题 | 建议 |
|---|---|
| OTP 请求格式不一致 | 1. 统飞书 OTP 卡片格式（见 SOUL.md §7）<br>2. 确保 request_id 绑定 OTP 代码 |
| OTP timeout 机制 | 1. 实现 progressive resend（5min → 15min → 30min → 60min）<br>2. 增加 @-user 决策逻辑 |
| Daemon 重启流程 | 1. 优化 restart_daemon() 函数<br>2. 增加 poll wait 逻辑<br>3. 检查 SSH socket closed 根因 |

---

### 3.8 Worker 脚本错误处理 🔧 **中优先级**

| 问题 | 建议 |
|---|---|
| Worker 执行失败时缺少日志 | 1. 在 Worker scripts 中增加 logging<br>2. 写入 `{batch_dir}/logs/worker_error.log` |
| 错误信息不够详细 | 1. 捕获完整 traceback<br>2. 发送飞书错误卡片包含详细信息 |

---

## 4. 总结

### 已修复问题
1. ✅ PYTHONPATH 泄漏 → Worker scripts 添加显式清除
2. ✅ 依赖链 race condition → 手动重建正确依赖链
3. ✅ Blocked Kanban 任务 → 手动 unblock
4. ✅ Manifest 更新不完整 → 手动修复状态文件
5. ✅ 状态机互锁 → 手动停止旧 workflow

### 待调查问题
1. ⏳ Watchdog 超时根因 → 需要检查测试执行时间、GPU 状态、Bastion 连接

### 待优化方面
1. 🔧 高优先级：PYTHONPATH 环境隔离、Kanban 任务调度优化
2. 🔧 中优先级：远程测试超时机制、Orchestrator 验证增强、Bastion daemon 管理、Worker 错误处理
3. 🔧 低优先级：飞书卡片更新优化、状态机互锁机制优化

---

## 5. 相关文件

| 文件 | 用途 |
|---|---|
| `tasks/ut/docs/reports/2026-06-24-L4-test-issues-and-fixes.md` | 本报告 |
| `skills/ut/workflow/scripts/hermes_runner.py` | Workflow runner 核心库 |
| `skills/ut/workflow/scripts/bastion_manager.py` | Bastion daemon 管理库 |
| `tests/ut/integration/fixtures/workflow.l4.yaml` | L4 frozen 配置 |
| `tests/ut/integration/fixtures/L4_expected.json` | L4 预期结果 baseline |

---

## 6. 下一步行动

1. **调查 Watchdog 超时根因**
   - 检查远程服务器 GPU 状态
   - 检查测试实际执行时间
   - 检查 Bastion daemon 连接稳定性

2. **更新 Worker SKILL 文档**
   - 添加 PYTHONPATH 泄漏 pitfall
   - 添加错误处理 best practice

3. **优化 Kanban 任务调度**
   - 实现 blocked 任务自动恢复
   - 实现依赖链状态验证

4. **优化 Bastion daemon 管理**
   - 实现 OTP progressive resend
   - 优化 daemon 重启流程

---

**报告生成**: 2026-06-24 22:15
**作者**: UT Supervisor Agent
