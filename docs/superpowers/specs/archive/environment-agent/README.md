# Environment Agent 设计

> **⚠️ DEPRECATED - 此Agent已移除**
> 
> **最新方案**: [../2026-06-08-agent-automation-design.md](../2026-06-08-agent-automation-design.md)
> 
> Environment Agent 已移除，职责合并到 Runner Agent：
> - GPU监控 → Runner启动时检查
> - 容器维护 → Runner测试前检查
> - 依赖下载 → **Runner自处理**
> - 冲突处理 → Runner记录并汇报

---

## 原设计（已废弃）

> **Agent协同系统 - Environment Agent (Claude Code)**
> **职责: GPU监控、容器维护、依赖下载、冲突处理**
> **创建日期: 2026-06-06**

---

## Agent信息

| 属性 | 值 |
|------|-----|
| Agent ID | `environment` |
| Agent类型 | Claude Code CLI |
| 终端窗口 | #3 |
| 状态文件 | `.agents/environment/status.json` |
| 消息文件 | `.agents/environment/messages.jsonl` |
| 接收文件 | `.agents/environment/inbox.jsonl` |
| Spec文件 | `docs/superpowers/specs/agents/environment-agent/README.md` |

---

## 核心职责

```
┌─────────────────────────────────────────────────────────────────┐
│                    Environment Agent职责                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ✅ GPU监控                                                      │
│  ├── 实时检查GPU空闲状态                                         │
│  ├── 检测抢占进程                                                │
│  ├── 记录GPU使用情况                                             │
│  └── 汇报GPU状态                                                 │
│                                                                  │
│  ✅ 容器维护                                                     │
│  ├── 检查Docker容器健康                                          │
│  ├── 处理容器异常重启                                            │
│  ├── 监控容器资源使用                                            │
│  └── 汇报容器状态                                                │
│                                                                  │
│  ✅ 依赖下载                                                     │
│  ├── 收到Supervisor请求后下载依赖                                │
│  ├── 在t_ascend下载后同步到t_h20                                │
│  ├── 使用huggingface-cli下载模型                                │
│  └── 汇报下载进度和结果                                          │
│                                                                  │
│  ✅ 冲突处理                                                     │
│  ├── 检测进程冲突                                                │
│  ├── 记录抢占进程PID                                             │
│  ├── 汇报冲突情况                                                │
│  │  （复杂冲突需人工介入）                                       │
│                                                                  │
│  ❌ 不负责                                                       │
│  ├── 不执行测试                                                  │
│  ├── 不处理Bastion连接                                           │
│  ├── 不发飞书通知                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 启动方式

```bash
# 启动Claude Code CLI
claude-code --workdir D:\workspace\apmm

# 启动后输入
"我是Environment Agent，启动环境监控..."
```

### 启动流程

```
Step 1: 读取配置
├── 读取 .agents/config.json
├── 获取 agent_id = "environment"
├── 获取文件路径

Step 2: 读取Spec文档
├── 读取 environment-agent/README.md
├── 了解职责边界

Step 3: 初始化状态
├── 写入 status.json = {"status": "starting"}
├── 清空 inbox.jsonl

Step 4: 发送启动通知
├── 写入 messages.jsonl:
│   {"type": "agent_started", "agent_id": "environment", ...}

Step 5: 进入监控循环
├── 更新 status.json = {"status": "running"}
├── 开始GPU监控
├── 开始容器监控
├── 定期检查inbox
└── 定期汇报状态
```

---

## 主循环逻辑

### GPU监控（每10秒）

```
┌─────────────────────────────────────────────────────────────────┐
│                    GPU监控流程                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  检查GPU状态:                                                    │
│  ├── 通过agent.py执行: nvidia-smi                               │
│  ├── 解析GPU使用情况                                             │
│  ├── 检测空闲GPU                                                 │
│  ├── 检测占用进程                                                │
│                                                                  │
│  检测抢占:                                                       │
│  ├── 如果GPU被非UT进程占用                                       │
│  ├── 记录进程PID                                                 │
│  ├── 发送 gpu_intrusion 消息                                    │
│                                                                  │
│  更新状态:                                                       │
│  ├── 更新status.json的gpu_status字段                             │
│  ├── 定期发送environment_status                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 容器监控（每30秒）

```
┌─────────────────────────────────────────────────────────────────┐
│                    容器监控流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  检查容器状态:                                                   │
│  ├── 通过agent.py执行: docker ps                                 │
│  ├── 检查v0.13.0_torch2.5.1_ut容器状态                          │
│  ├── 检查容器资源使用                                            │
│                                                                  │
│  处理异常:                                                       │
│  ├── 如果容器停止 → 尝试重启                                     │
│  ├── 如果重启失败 → 发送container_error                          │
│                                                                  │
│  更新状态:                                                       │
│  ├── 更新status.json的container_status字段                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 汇报给Supervisor的场景

| 消息类型 | 触发条件 | 优先级 | 数据内容 |
|----------|----------|:------:|----------|
| `agent_started` | Agent启动完成 | P2 | 启动时间 |
| `gpu_intrusion` | GPU被非UT进程占用 | P0 | 占用GPU列表、占用进程PID |
| `cpu_intrusion` | CPU被非UT进程占用大量 | P1 | cpu_usage、占用进程 |
| `container_error` | 容器异常/崩溃 | P0 | 容器名、错误信息 |
| `dependency_ready` | 依赖下载完成 | P2 | 依赖名、下载位置 |
| `dependency_failed` | 依赖下载失败 | P0 | 依赖名、失败原因 |
| `environment_status` | 定时汇报（每分钟） | P2 | GPU状态、容器状态 |

---

## inbox消息处理

| 收到消息类型 | 动作 |
|--------------|------|
| `download_dependency` | 启动依赖下载流程 |
| `download_model` | 使用huggingface-cli下载模型 |
| `check_gpu_intrusion` | 详细检查GPU占用情况 |
| `release_gpu` | 尝试协调释放GPU（可能失败需人工） |
| `restart_container` | 重启指定容器 |

---

## 依赖下载流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    依赖下载流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: 收到Supervisor请求                                      │
│  ├── inbox.jsonl: {"type": "download_dependency",               │
│  │                 "name": "meta-llama/Llama-3.2-1B-Instruct"}  │
│                                                                  │
│  Step 2: 判断下载位置                                            │
│  ├── Python包 → t_ascend下载后pip install到t_h20                │
│  ├── HF模型 → huggingface-cli下载到t_h20 hf_hub/                │
│                                                                  │
│  Step 3: 执行下载                                                │
│  ├── 通过agent.py执行下载命令                                    │
│  ├── 监控下载进度                                                │
│  ├── 更新status.json: {"status": "downloading"}                 │
│                                                                  │
│  Step 4: 下载完成                                                │
│  ├── 验证下载结果                                                │
│  ├── 发送 dependency_ready 消息                                 │
│  ├── 更新status.json: {"status": "running"}                     │
│                                                                  │
│  Step 5: 下载失败                                                │
│  ├── 记录失败原因                                                │
│  ├── 发送 dependency_failed 消息                                │
│  │  （需人工介入处理）                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 需人工介入的场景

| 场景 | 原因 | 用户操作 |
|------|------|----------|
| GPU抢占冲突 | 其他进程拒绝释放GPU | 手动终止进程或协调 |
| 容器无法恢复 | Docker异常 | 手动重启Docker/容器 |
| 下载失败 | 网络/权限问题 | 手动下载或调整权限 |
| Python包冲突 | 版本不兼容 | 手动解决依赖冲突 |

---

## 终端用户指令

用户在Environment终端可直接输入：

| 指令 | 动作 |
|------|------|
| `我的状态` | 输出status.json |
| `GPU状态` | 输出GPU详细信息 |
| `容器状态` | 输出容器详细信息 |
| `下载模型 xxx` | 手动触发模型下载 |
| `检查GPU抢占` | 详细检查GPU占用进程 |
| `汇报状态` | 手动发送environment_status |

---

## 相关文档

- [gpu-monitoring.md](./gpu-monitoring.md) - GPU监控详细设计
- [container-management.md](./container-management.md) - 容器管理详细设计
- [dependency-handling.md](./dependency-handling.md) - 依赖处理详细设计
- [conflict-resolution.md](./conflict-resolution.md) - 冲突解决详细设计

---

*创建日期: 2026-06-06*