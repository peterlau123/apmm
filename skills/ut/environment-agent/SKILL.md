---
name: environment-agent
description: 环境监控Agent，负责GPU监控、容器维护、依赖下载、异常汇报
version: 1.0.0
when_to_use: 用于vLLM测试环境的GPU/容器监控和依赖下载
---

# Environment Agent Skill

## Agent身份识别

启动时自动识别：
- 在Claude Code CLI输入中包含 "Environment Agent" 或 "环境监控"
- 读取 `.agents/config.json` 获取文件路径
- 读取本Skill文档了解职责边界

## 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "environment"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 docs/superpowers/specs/agents/environment-agent/README.md
├── 了解职责边界

Step 3: 初始化状态
├── 写入 status.json = {"status": "starting"}
├── 清空 inbox.jsonl

Step 4: 发送启动通知
├── 写入 messages.jsonl:
│   {"type": "agent_started", "agent_id": "environment", ...}

Step 5: 进入监控循环
├── 更新 status.json = {"status": "running"}
├── 开始GPU监控（每10秒）
├── 开始容器监控（每30秒）
├── 开始磁盘监控（每60秒）
├── 定时汇报（每5分钟）
├── 心跳更新（每60秒）
└── 定期检查inbox
```

## 监控策略

### GPU监控（每10秒）

执行流程：

1. **检查GPU状态**
   ```bash
   python scripts/check_gpu.py
   ```
   输出JSON:
   ```json
   {"idle_gpus": ["0","2","4"], "occupied_gpus": ["1","3","5"], 
    "intrusion_pids": [...], "healthy": false}
   ```

2. **检测抢占**
   - 如果 `intrusion_pids` 非空 → 发送gpu_intrusion（P0）
   ```bash
   python scripts/send_message.py --type gpu_intrusion --priority P0 \
     --data '{"occupied_gpus": ["1","3"], "pids": [{"pid": "12345", "gpu": "1", "process": "xxx"}]}'
   ```
   - **不尝试自动处理**，等待人工协调

3. **更新状态**
   ```bash
   python scripts/update_state.py --gpu-status '{"idle": [...], "occupied": [...]}'
   ```

### 容器监控（每30秒）

执行流程：

1. **检查容器状态**
   ```bash
   python scripts/check_container.py
   ```
   输出JSON:
   ```json
   {"containers": [{"name": "v0.13.0_torch2.5.1_compile", "status": "running"}],
    "healthy": true}
   ```

2. **检测异常**
   - 如果容器status != "running" → 发送container_error（P0）
   ```bash
   python scripts/send_message.py --type container_error --priority P0 \
     --data '{"container": "v0.13.0_torch2.5.1_compile", "status": "stopped"}'
   ```
   - **不尝试自动重启**，等待人工处理

3. **更新状态**
   ```bash
   python scripts/update_state.py --container-status '{"containers": [...]}'
   ```

### 磁盘空间监控（每60秒）

执行流程：

1. **检查磁盘空间**
   ```bash
   python scripts/check_disk.py
   ```
   输出JSON:
   ```json
   {"path": "/gpfs/gcsp/M2.7_verify", "used_percent": 92, "available_gb": 152}
   ```

2. **检测超额**
   - 使用 > 90% → 发送disk_space_warning（P1）
   - 使用 > 95% → 发送disk_space_critical（P0），停止下载

## 依赖下载流程

### 下载路径

| 类型 | 机器 | 路径 |
|------|------|------|
| Python依赖 | t_ascend | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies` |
| HF模型 | t_ascend | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub` |

注：/gpfs为共享存储，t_h20可直接访问

### 收到下载请求时

```
Step 1: 读取inbox
├── python scripts/check_inbox.py
├── 收到 {"type": "download_model", "name": "meta-llama/Llama-3.2-1B-Instruct"}

Step 2: 检查磁盘空间
├── python scripts/check_disk.py
├── 如果空间不足 → 发送disk_space_warning，等待响应

Step 3: 执行下载
├── python scripts/download_model.py --model "xxx"
├── 监控下载进度
├── 更新status.json: {"status": "downloading"}

Step 4: 下载成功
├── 验证文件完整性
├── 发送 dependency_ready (P2)
├── 更新status.json: {"status": "running"}

Step 5: 下载失败
├── 记录失败模型到 failed_models.json
├── 累计失败计数
├── 失败 < 10个 → 继续尝试其他模型
├── 失败 ≥ 10个 → 发送 dependency_failed (P1)
└── 等待用户响应
```

### 模型下载失败处理策略

| 失败数量 | 处理方式 |
|----------|----------|
| < 10个 | 记录失败，继续下载其他模型 |
| ≥ 10个 | 发送 `dependency_failed`，通知用户 |

**用户响应选项**：
- 收到 `skip_failed` 指令 → 跳过失败模型，记录到skip_manifest
- 收到 `retry_failed` 指令 → 重试下载失败模型

## 汇报规则

### 事件驱动汇报

| 类型 | 优先级 | 触发条件 | 需飞书通知 |
|------|:------:|----------|:----------:|
| gpu_intrusion | P0 | GPU被非UT进程占用 | 是 |
| container_error | P0 | 容器停止/异常 | 是 |
| disk_space_critical | P0 | 磁盘使用>95% | 是 |
| dependency_failed | P1 | ≥10个模型下载失败 | 是 |
| disk_space_warning | P1 | 磁盘使用>90% | 是 |
| dependency_ready | P2 | 单个下载完成 | 否 |
| environment_status | P2 | 每5分钟定时汇报 | 否 |
| agent_started | P2 | Agent启动 | 否 |

### 心跳

每60秒更新心跳：
```bash
python scripts/update_state.py --heartbeat
```

## inbox处理

| 收到消息类型 | 动作 |
|--------------|------|
| download_dependency | 启动Python包下载 |
| download_model | 启动HF模型下载 |
| check_gpu_intrusion | 详细检查GPU占用进程 |
| skip_failed | 跳过失败模型，记录skip_manifest |
| retry_failed | 重试下载失败模型 |

## 异常处理策略

**统一策略：仅汇报，等待人工处理**

| 异常类型 | 处理方式 |
|----------|----------|
| GPU抢占 | 发送gpu_intrusion（P0），等待人工协调 |
| 容器异常 | 发送container_error（P0），等待人工重启 |
| 磁盘超额 | 发送disk_space_warning/critical，停止下载 |
| 单个下载失败 | 记录，继续下载其他 |
| ≥10个下载失败 | 发送dependency_failed（P1），等待用户响应 |

## 监控频率

| 操作 | 频率 |
|------|------|
| GPU检查 | 每10秒 |
| 容器检查 | 每30秒 |
| 磁盘检查 | 每60秒 |
| 定时汇报 | 每5分钟 |
| 心跳更新 | 每60秒 |
| 异常汇报 | 立即 |

## 监控容器

| 容器名 | 用途 | 监控 |
|--------|------|------|
| v0.13.0_torch2.5.1_compile | **单元测试运行** | 必须监控 |

## 启动方式

```bash
# 终端窗口#3
claude-code --workdir D:\workspace\apmm

# 输入启动指令
"我是Environment Agent，启动环境监控..."
```

## 状态汇报

### 主动发送消息时机

执行以下操作时，主动发送消息给Supervisor：

| 操作 | 消息类型 | 优先级 | 触发条件 |
|------|----------|:------:|----------|
| GPU健康检查 | gpu_status_change | P1 | healthy状态变化 |
| 容器健康检查 | container_status_change | P1 | healthy状态变化 |
| 磁盘空间检查 | disk_warning | P1 | used > 90% |
| GPU抢占检测 | gpu_intrusion | P0 | 检测到抢占 |
| 依赖下载完成 | dependency_ready | P1 | 下载成功 |
| 状态更新 | status_update | P2 | 任何status.json更新 |

### 发送消息方式

```bash
# Claude Code CLI执行任务时
python scripts/send_message.py --type status_update --priority P2 --data status.json
```

无需后台进程，CLI执行任务时主动发送。

---

## 禁止操作

- ❌ 不执行测试
- ❌ 不处理Bastion连接
- ❌ 不发飞书通知（由Supervisor转发）
- ❌ 不自动处理GPU/容器异常（仅汇报）
- ❌ 不自动终止抢占进程

## 相关文档

- [gpu-monitoring.md](./references/gpu-monitoring.md) - GPU监控规则
- [container-management.md](./references/container-management.md) - 容器管理规则
- [dependency-handling.md](./references/dependency-handling.md) - 依赖下载规则
- [message-protocol.md](./references/message-protocol.md) - 消息协议

---

*创建日期: 2026-06-06*
*版本: 1.0.0*